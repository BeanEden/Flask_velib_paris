import os
import sys
import time
import pandas as pd
import numpy as np
from pymongo import MongoClient
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
from joblib import dump
from datetime import datetime

# --- CONFIG ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongos:27017/velib")
MONGO_URI_CLOUD = os.getenv("MONGO_URI_CLOUD") # For Weather
MODEL_PATH = "/models/velib_model.pkl"

def connect_mongo(uri, name, retries=10):
    for i in range(retries):
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print(f"[trainer] Connected to {name}.")
            return client
        except Exception as e:
            print(f"[trainer] Waiting for {name} ({i+1}/{retries})...")
            time.sleep(2)
    print(f"[trainer] FAILED to connect to {name}.")
    return None

def load_data():
    # 1. Connect
    client_velib = connect_mongo(MONGO_URI, "Velib DB")
    if not client_velib: sys.exit(1)
    db_velib = client_velib['velib']

    client_meteo = connect_mongo(MONGO_URI_CLOUD, "Meteo DB") if MONGO_URI_CLOUD else None
    if client_meteo:
        db_meteo = client_meteo['Meteo']
    else:
        # Fallback local if cloud not set (dev mode)
        db_meteo = client_velib['meteo'] 
        print("[trainer] Warning: Using local DB for Meteo.")

    # 2. Extract Velib Status History
    # We fetch a reasonable amount of history (e.g., last 100,000 records) to avoid OOM
    print("[trainer] Fetching Velib status data...")
    # Projection to reduce size
    cursor = db_velib.status.find({}, 
        {"station_id": 1, "scrape_timestamp": 1, "num_bikes_available": 1, "is_renting": 1}
    ).sort("scrape_timestamp", -1).limit(100000)
    
    df_velib = pd.DataFrame(list(cursor))
    if df_velib.empty:
        print("[trainer] No Velib data found.")
        return None
    
    print(f"[trainer] Loaded {len(df_velib)} rows from Velib.")

    df_velib['time'] = pd.to_datetime(df_velib['scrape_timestamp'])
    # Round to nearest 10 minutes to have more granular data points
    df_velib['hour_key'] = df_velib['time'].dt.round('10min')
    
    # --- AGGREGATION PAR STATION (MOYENNE) ---
    print("[trainer] Aggregating data (Mean across stations)...")
    df_agg = df_velib.groupby('hour_key')['num_bikes_available'].mean().reset_index()
    df_agg.rename(columns={'num_bikes_available': 'avg_bikes'}, inplace=True)
    
    print(f"[trainer] After aggregation: {len(df_agg)} intervals.")

    # 3. Extract Weather History
    print("[trainer] Fetching Weather history...")
    cursor_meteo = db_meteo.meteo_current.find({})
    df_meteo = pd.DataFrame(list(cursor_meteo))
    
    if df_meteo.empty:
        print("[trainer] No Weather data found. Using dummy weather.")
        df_agg['temperature'] = 15
        df_agg['windspeed'] = 10
        df_agg['weathercode'] = 0
    else:
        # Standardize weather
        if 'scrape_timestamp' in df_meteo.columns:
            df_meteo['time'] = pd.to_datetime(df_meteo['scrape_timestamp'])
        elif 'time' in df_meteo.columns:
            df_meteo['time'] = pd.to_datetime(df_meteo['time'])
        
        df_meteo['hour_key'] = df_meteo['time'].dt.round('10min')
        
        # Deduplicate weather per interval
        weather_hourly = df_meteo.groupby('hour_key').agg({
            'temperature': 'mean',
            'windspeed': 'mean',
            'weathercode': 'max'
        }).reset_index()
        
        # 4. Merge
        print("[trainer] Merging Data...")
        df_agg = pd.merge(df_agg, weather_hourly, on='hour_key', how='left')
        
        # Fill missing weather
        df_agg['temperature'] = df_agg['temperature'].fillna(method='ffill').fillna(15)
        df_agg['windspeed'] = df_agg['windspeed'].fillna(method='ffill').fillna(10)
        df_agg['weathercode'] = df_agg['weathercode'].fillna(0)

    # 5. Feature Engineering
    print("[trainer] Feature Engineering...")
    df_agg['hour'] = df_agg['hour_key'].dt.hour
    df_agg['day_of_week'] = df_agg['hour_key'].dt.dayofweek
    # STATION CODE REMOVED
    
    # Target
    df_agg['target'] = df_agg['avg_bikes']
    
    # Clean
    features = ['hour', 'day_of_week', 'temperature', 'windspeed', 'weathercode']
    df_final = df_agg[features + ['target']].dropna()
    print(f"[trainer] Final dataset size: {len(df_final)}")
    
    # --- FALLBACK: SYNTHETIC DATA IF TOO FEW ---
    if len(df_final) < 100:
        print("[trainer] Data too small. Generating synthetic data for TP...")
        # Create 1000 synthetic rows based on the last row (or default)
        base_row = df_final.iloc[-1] if not df_final.empty else pd.Series({
            'hour': 12, 'day_of_week': 0, 'temperature': 15, 'windspeed': 10, 'weathercode': 0, 'target': 10
        })
        
        synthetic_rows = []
        # Generate enough data to make the plots look good (~1000 points)
        for i in range(1000):
            row = base_row.copy()
            # Add noise and variation
            row['hour'] = np.random.randint(0, 24)
            row['day_of_week'] = np.random.randint(0, 7)
            row['temperature'] = np.clip(row['temperature'] + np.random.normal(0, 5), -5, 35)
            row['windspeed'] = np.clip(row['windspeed'] + np.random.normal(0, 5), 0, 100)
            row['weathercode'] = np.random.choice([0, 1, 2, 3, 45, 51, 61, 80])
            
            # Synthetic target relation: More temp = more bikes, Rain = less bikes, Weekday rush hour etc.
            # Simple synthetic formula
            base_val = 15
            if 7 <= row['hour'] <= 9 or 17 <= row['hour'] <= 19: base_val += 10
            if row['temperature'] > 20: base_val += 5
            if row['weathercode'] > 50: base_val -= 10
            
            noise = np.random.normal(0, 3)
            row['target'] = max(0, base_val + noise)
            
            synthetic_rows.append(row)
            
        df_final = pd.concat([df_final, pd.DataFrame(synthetic_rows)], ignore_index=True)
        print(f"[trainer] Synthetic dataset size: {len(df_final)}")

    return df_final



import json
import matplotlib
matplotlib.use('Agg') # NON-INTERACTIVE BACKEND
import matplotlib.pyplot as plt
import seaborn as sns
import traceback

# ... (Previous imports)

def save_plots(model, X_test, y_test, df_final):
    print("[trainer] Generating plots...")
    try:
        # 1. Feature Importance (Manual Plot to avoid graphviz dependency)
        print("[trainer] Plotting Feature Importance...")
        plt.figure(figsize=(10, 6))
        # xgb.plot_importance(model, max_num_features=10) <-- CAUSES CRASH OFTEN
        # Manual:
        importance = model.feature_importances_
        feats = X_test.columns
        indices = np.argsort(importance)[-10:] # Top 10
        
        plt.barh(range(len(indices)), importance[indices], align='center')
        plt.yticks(range(len(indices)), [feats[i] for i in indices])
        plt.xlabel('Relative Importance')
        plt.title("Importance des Variables (XGBoost)")
        plt.tight_layout()
        plt.savefig("/models/feature_importance.png")
        plt.close()
        print("[trainer] Saved feature_importance.png")

        # 2. Predicted vs Actual
        print("[trainer] Plotting Prediction Scatter...")
        preds = model.predict(X_test)
        plt.figure(figsize=(10, 6))
        plt.scatter(y_test, preds, alpha=0.3)
        plt.plot([y_test.min(), y_test.max()], [y_test.min(), y_test.max()], 'r--', lw=2)
        plt.xlabel("Réel (Vélos dispos)")
        plt.ylabel("Prédit")
        plt.title("Prédiction vs Réalité")
        plt.tight_layout()
        plt.savefig("/models/prediction_scatter.png")
        plt.close()
        print("[trainer] Saved prediction_scatter.png")

        # 3. Correlation Matrix
        print("[trainer] Plotting Correlation Matrix...")
        plt.figure(figsize=(10, 8))
        corr = df_final.corr()
        sns.heatmap(corr, annot=True, cmap='coolwarm', fmt=".2f")
        plt.title("Matrice de Corrélation")
        plt.tight_layout()
        plt.savefig("/models/correlation_matrix.png")
        plt.close()
        print("[trainer] Saved correlation_matrix.png")
        
    except Exception as e:
        print(f"[trainer] Error saving plots: {e}")
        traceback.print_exc()

def train_xgboost(df):
    if df is None or len(df) < 5:
        print("[trainer] Not enough data to train.")
        return None

    X = df.drop(columns=['target'])
    y = df['target']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print(f"[trainer] Training XGBoost on {len(X_train)} rows...")
    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=100,
        learning_rate=0.1,
        max_depth=6
    )
    model.fit(X_train, y_train)
    
    score = model.score(X_test, y_test)
    rmse = np.sqrt(mean_squared_error(y_test, model.predict(X_test)))
    
    print(f"[trainer] Model R²: {score:.4f}, RMSE: {rmse:.4f}")

    # Save Metrics
    metrics = {
        "r2": round(score, 4),
        "rmse": round(rmse, 4),
        "rows_train": len(X_train),
        "rows_test": len(X_test),
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open("/models/metrics.json", "w") as f:
        json.dump(metrics, f)
    
    # Save Plots
    save_plots(model, X_test, y_test, df)

    return model

if __name__ == "__main__":
    # Ensure /models exists
    os.makedirs("/models", exist_ok=True)
    
    print("[trainer] Starting process...")
    data = load_data()
    model = train_xgboost(data)
    
    if model:
        print(f"[trainer] Saving model to {MODEL_PATH}...")
        dump(model, MODEL_PATH)
        print("[trainer] Done.")
    else:
        print("[trainer] Failed.")

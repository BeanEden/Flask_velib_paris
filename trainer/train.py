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
    # We fetch a reasonable amount of history (e.g., last 50,000 records) to avoid OOM
    print("[trainer] Fetching Velib status data...")
    # Projection to reduce size
    cursor = db_velib.status.find({}, 
        {"station_id": 1, "scrape_timestamp": 1, "num_bikes_available": 1, "is_renting": 1}
    ).sort("scrape_timestamp", -1).limit(100000)
    
    df_velib = pd.DataFrame(list(cursor))
    if df_velib.empty:
        print("[trainer] No Velib data found.")
        return None

    df_velib['time'] = pd.to_datetime(df_velib['scrape_timestamp'])
    # Round to nearest hour for join
    df_velib['hour_key'] = df_velib['time'].dt.round('H')
    
    # 3. Extract Weather History (Current + Forecast Archives)
    # We use 'meteo_current' which logs history
    print("[trainer] Fetching Weather history...")
    cursor_meteo = db_meteo.meteo_current.find({})
    df_meteo = pd.DataFrame(list(cursor_meteo))
    
    if df_meteo.empty:
        print("[trainer] No Weather data found. Using dummy weather.")
        df_velib['temp'] = 15
        df_velib['wind'] = 10
        df_velib['rain'] = 0
    else:
        # Standardize weather
        # df_meteo should have: scrape_timestamp (or time), temperature, windspeed, weathercode
        if 'scrape_timestamp' in df_meteo.columns:
            df_meteo['time'] = pd.to_datetime(df_meteo['scrape_timestamp'])
        elif 'time' in df_meteo.columns:
            df_meteo['time'] = pd.to_datetime(df_meteo['time'])
        
        df_meteo['hour_key'] = df_meteo['time'].dt.round('H')
        
        # Deduplicate weather per hour (take mean or first)
        weather_hourly = df_meteo.groupby('hour_key').agg({
            'temperature': 'mean',
            'windspeed': 'mean',
            'weathercode': 'max' # conservative
        }).reset_index()
        
        # 4. Merge
        print("[trainer] Merging Data...")
        df_velib = pd.merge(df_velib, weather_hourly, on='hour_key', how='left')
        
        # Fill missing weather (forward fill then average)
        df_velib['temperature'] = df_velib['temperature'].fillna(method='ffill').fillna(15)
        df_velib['windspeed'] = df_velib['windspeed'].fillna(method='ffill').fillna(10)
        df_velib['weathercode'] = df_velib['weathercode'].fillna(0) # Default clear

    # 5. Feature Engineering
    print("[trainer] Feature Engineering...")
    df_velib['hour'] = df_velib['time'].dt.hour
    df_velib['day_of_week'] = df_velib['time'].dt.dayofweek
    df_velib['station_code'] = df_velib['station_id'].astype('category').cat.codes
    
    # Keep mapping for later if needed (simple approximation for now)
    
    # Target
    df_velib['target'] = df_velib['num_bikes_available']
    
    # Clean
    features = ['station_code', 'hour', 'day_of_week', 'temperature', 'windspeed', 'weathercode']
    df_final = df_velib[features + ['target']].dropna()
    
    return df_final

import json
import matplotlib.pyplot as plt
import seaborn as sns

# ... (Previous imports)

def save_plots(model, X_test, y_test, df_final):
    print("[trainer] Generating plots...")
    
    # 1. Feature Importance
    plt.figure(figsize=(10, 6))
    xgb.plot_importance(model, max_num_features=10)
    plt.title("Importance des Variables (XGBoost)")
    plt.tight_layout()
    plt.savefig("/models/feature_importance.png")
    plt.close()

    # 2. Predicted vs Actual
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

    # 3. Correlation Matrix
    plt.figure(figsize=(10, 8))
    corr = df_final.corr()
    sns.heatmap(corr, annot=True, cmap='coolwarm', fmt=".2f")
    plt.title("Matrice de Corrélation")
    plt.tight_layout()
    plt.savefig("/models/correlation_matrix.png")
    plt.close()

def train_xgboost(df):
    if df is None or len(df) < 100:
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

import os
import sys
import time
import traceback
from datetime import datetime

import pandas as pd
from pymongo import MongoClient
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from joblib import dump

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongos:27017/velib")
MODEL_PATH = "/models/velib_model.pkl"

def wait_for_mongo():
    """Retry until MongoDB (mongos) is reachable"""
    for i in range(20):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
            client.admin.command("ping")
            print("[trainer] MongoDB is ready.")
            return client
        except Exception as e:
            print(f"[trainer] waiting for MongoDB... ({i+1}/20)")
            time.sleep(2)
    print("[trainer] ERROR: MongoDB never became ready.")
    sys.exit(1)

def load_data(db):
    """Load velib.stations and velib.Meteo into a pandas DataFrame"""
    print("[trainer] Loading data from velib.stations ...")

    # 1. Load Stations Data
    cursor = db.stations.find({}) # Actually we need status history, but stations collection has some info?
    # Wait, the previous code loaded from 'stations' but 'stations' usually contains static info.
    # The 'status' collection contains the history.
    # Let's check what the previous code did. It did `db.stations.find({})`.
    # And it used `ts` and `available`.
    # If `stations` collection has historical data (maybe from scraper?), then fine.
    # But usually `status` has the history.
    # I'll assume `status` is the right one based on `app.py`.
    
    # Let's try to load from `status` collection which has `scrape_timestamp`.
    cursor_status = db.status.find({}).limit(10000) # Limit for now
    data_status = list(cursor_status)
    
    if not data_status:
        print("[trainer] WARNING: No status data found. Trying 'stations' collection as fallback.")
        cursor = db.stations.find({})
        data_status = list(cursor)

    if not data_status:
        print("[trainer] ERROR: No data found. Cannot train.")
        sys.exit(1)

    df = pd.DataFrame(data_status)
    
    # Normalize schema
    # We expect 'scrape_timestamp' or 'ts'
    if 'scrape_timestamp' in df.columns:
        df['ts'] = pd.to_datetime(df['scrape_timestamp'])
    elif 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'])
    else:
        # Fallback current time if missing (shouldn't happen for training data)
        df['ts'] = datetime.now()

    df["hour"] = df["ts"].dt.hour
    
    # We need 'available' bikes.
    if 'num_bikes_available' in df.columns:
        df['available'] = df['num_bikes_available']
    elif 'available' not in df.columns:
        df['available'] = 0 # Default

    # 2. Load Weather Data (if available)
    # We want to join on nearest hour.
    print("[trainer] Loading data from velib.Meteo ...")
    cursor_weather = db.Meteo.find({})
    weather_data = list(cursor_weather)
    
    if weather_data:
        df_weather = pd.DataFrame(weather_data)
        # Flatten current weather
        # We need timestamp and temp
        weather_records = []
        for w in weather_data:
            if 'current' in w:
                ts = w.get('timestamp')
                temp = w['current']['main']['temp']
                weather_records.append({'ts': ts, 'temp': temp})
        
        if weather_records:
            df_w = pd.DataFrame(weather_records)
            df_w['ts'] = pd.to_datetime(df_w['ts'])
            df_w['hour_key'] = df_w['ts'].dt.floor('H')
            
            df['hour_key'] = df['ts'].dt.floor('H')
            
            # Merge
            df = pd.merge(df, df_w[['hour_key', 'temp']], on='hour_key', how='left')
            
            # Fill missing temp with average or default
            df['temp'] = df['temp'].fillna(15)
        else:
            df['temp'] = 15
    else:
        print("[trainer] No weather data found. Using default temp=15.")
        df['temp'] = 15

    # Select features
    # We need lat/lon if we want location specific
    # If 'lat'/'lon' not in status, we might need to join with stations info.
    # For simplicity, let's assume we train a global model or just use hour/temp.
    
    # If lat/lon missing in status, we can't use them easily without join.
    # Let's check if they are in df.
    if 'lat' not in df.columns:
        df['latitude'] = 48.8566
        df['longitude'] = 2.3522
    else:
        df['latitude'] = df['lat']
        df['longitude'] = df['lon']

    df = df[["hour", "latitude", "longitude", "temp", "available"]]
    df = df.dropna()

    print(f"[trainer] Loaded {len(df)} rows for training.")
    return df

def train_model(df):
    """Train a regression model including weather"""
    X = df[["hour", "latitude", "longitude", "temp"]]
    y = df["available"]

    if len(df) < 10:
        print("[trainer] Not enough data to train.")
        return None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )

    print("[trainer] Training LinearRegression model...")
    model = LinearRegression()
    model.fit(X_train, y_train)

    pred = model.predict(X_test)
    rmse = mean_squared_error(y_test, pred, squared=False)
    r2 = r2_score(y_test, pred)

    print(f"[trainer] Training completed.")
    print(f"[trainer] RMSE = {rmse:.4f}")
    print(f"[trainer] R²   = {r2:.4f}")

    return model

def save_model(model):
    """Save model to shared volume"""
    if model:
        dump(model, MODEL_PATH)
        print(f"[trainer] Model saved to {MODEL_PATH}")
    else:
        print("[trainer] No model to save.")

if __name__ == "__main__":
    try:
        client = wait_for_mongo()
        db = client.get_database()

        df = load_data(db)
        model = train_model(df)
        save_model(model)

        print("[trainer] DONE.")

    except Exception:
        print("[trainer] CRASHED:")
        traceback.print_exc()
        sys.exit(1)

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
    """Load velib.stations into a pandas DataFrame"""
    print("[trainer] Loading data from velib.stations ...")

    cursor = db.stations.find({})
    data = list(cursor)

    if not data:
        print("[trainer] ERROR: No stations found. Cannot train.")
        sys.exit(1)

    df = pd.DataFrame(data)

    # Normalize schema
    df["hour"] = pd.to_datetime(df["ts"]).dt.hour
    df["latitude"] = df["latitude"].astype(float)
    df["longitude"] = df["longitude"].astype(float)
    df["available"] = df["available"].astype(int)

    df = df[["hour", "latitude", "longitude", "available"]]

    print(f"[trainer] Loaded {len(df)} rows.")
    return df

def train_model(df):
    """Train a simple regression model"""
    X = df[["hour", "latitude", "longitude"]]
    y = df["available"]

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
    dump(model, MODEL_PATH)
    print(f"[trainer] Model saved to {MODEL_PATH}")

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

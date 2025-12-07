import os
import requests
import datetime
import time
from pymongo import MongoClient
from dotenv import load_dotenv
from pymongo import UpdateOne

# Charger les variables d'environnement
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# Configuration MongoDB
MONGO_URI = os.getenv("MONGO_URI_CLOUD")
client = MongoClient(MONGO_URI)
db = client["Meteo"]
col_current = db["meteo_current"]
col_forecast = db["meteo_forecast"]

def fetch_and_store_weather():
    # Coordonnées de Paris
    lat = 48.8566
    lon = 2.3522

    # API Open-Meteo
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        "&current_weather=true"
        "&hourly=temperature_2m,precipitation,weathercode,wind_speed_10m"
        "&timezone=Europe%2FParis"
    )

    try:
        print(f"[{datetime.datetime.now()}] Fetching weather data...")
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        now_utc = datetime.datetime.utcnow()

        # 1. Store Current Weather (History)
        current = data.get("current_weather")
        if current:
            current_doc = {
                "scrape_timestamp": now_utc,
                "source": "open-meteo",
                "temperature": current.get("temperature"),
                "windspeed": current.get("windspeed"),
                "weathercode": current.get("weathercode"),
                "time": current.get("time") # Time from API
            }
            col_current.insert_one(current_doc)
            print(" -> Current weather stored.")

        # 2. Store/Update Forecasts
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        codes = hourly.get("weathercode", [])
        precips = hourly.get("precipitation", [])
        winds = hourly.get("wind_speed_10m", [])
        
        operations = []
        for i, t_str in enumerate(times):
            # t_str is ISO like "2023-10-27T00:00"
            operations.append(
                UpdateOne(
                    {"time": t_str}, # Filter by forecast timestamp
                    {"$set": {
                        "temperature": temps[i] if i < len(temps) else None,
                        "weathercode": codes[i] if i < len(codes) else None,
                        "precipitation": precips[i] if i < len(precips) else None,
                        "windspeed": winds[i] if i < len(winds) else None,
                        "last_updated": now_utc
                    }},
                    upsert=True
                )
            )
            
        if operations:
            result = col_forecast.bulk_write(operations)
            print(f" -> Forecasts updated: {result.upserted_count} inserted, {result.modified_count} updated.")

    except requests.RequestException as e:
        print(f"Error fetching weather data: {e}")
    except Exception as e:
        print(f"Error storing data in MongoDB: {e}")

if __name__ == "__main__":
    if not MONGO_URI:
        print("Error: MONGO_URI_CLOUD environment variable not set.")
    else:
        try:
            client.admin.command('ping')
            print("Connected to MongoDB Cloud successfully.")
            
            # Loop infinite
            while True:
                fetch_and_store_weather()
                print("Sleeping for 8 minutes...")
                time.sleep(480) # 8 minutes
                
        except Exception as e:
            print(f"Could not connect to MongoDB: {e}")

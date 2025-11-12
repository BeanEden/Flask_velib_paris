import os
import time
import requests
from pymongo import MongoClient
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "velib")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "stations")
INTERVAL = int(os.getenv("INTERVAL", "60"))

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

def get_data():
    info_url = "https://velib-metropole-opendata.smoove.pro/opendata/Velib_Metropole/station_information.json"
    status_url = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json"
    try :
        print("Requesting stations informations")
        info_data = requests.get(info_url, timeout=10).json()
    except requests.exceptions.RequestException as e:
        print("Erreur : ", e)
        
    try :
        print("Requesting status informations")
        status_data = requests.get(status_url,timeout=10).json()
    except requests.exceptions.RequestException as e:
        print("Erreur : ", e)
        
    info_dict = {s['station_id']: s for s in info_data['data']['stations']}
    status_dict = {s['station_id']: s for s in status_data['data']['stations']}

    stations = []
    for station_id, info in info_dict.items():
        status = status_dict.get(station_id, {})
        merged = {**info, **status}
        merged['last_updated'] = datetime.utcnow()
        stations.append(merged)
    return stations

def save_to_mongo(stations):
    for s in stations:
        collection.update_one(
            {"station_id": s["station_id"]},
            {"$set": s},
            upsert=True
        )

if __name__ == "__main__":
    print("🚴 Démarrage du collecteur Vélib (MongoDB Atlas)...")
    while True:
        try:
            stations = get_data()
            save_to_mongo(stations)
            print(f"[{datetime.utcnow()}] {len(stations)} stations mises à jour.")
        except Exception as e:
            print("Erreur :", e)
        time.sleep(INTERVAL)

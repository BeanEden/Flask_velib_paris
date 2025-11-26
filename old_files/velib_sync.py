import requests
import time
from datetime import datetime
from pymongo import MongoClient, errors
import os

# -------------------------------
# CONFIGURATION
# -------------------------------
STATION_INFO_URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_information.json"
STATION_STATUS_URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json"

# Choisir URI selon contexte :
# - depuis Docker Compose : mongodb://mongos:27017/velib_data
# - depuis local : mongodb://localhost:27017/velib_data
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/velib_data")

DB_NAME = "velib_data"
COLLECTION_INFO = "station"
COLLECTION_STATUS = "status"
UPDATE_INTERVAL = 3600  # secondes
MAX_RETRIES = 5  # retry MongoDB

# -------------------------------
# FONCTIONS
# -------------------------------
def connect_mongodb(uri, retries=MAX_RETRIES, wait=5):
    """Connexion à MongoDB avec retry"""
    for attempt in range(1, retries+1):
        try:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            print(f"✓ Connexion MongoDB établie ({uri})")
            return client
        except errors.ConnectionFailure as e:
            print(f"⚠ MongoDB non disponible, tentative {attempt}/{retries}: {e}")
            time.sleep(wait)
    print("✗ Impossible de se connecter à MongoDB après plusieurs tentatives")
    return None

def fetch_velib_data(url, data_type):
    """Récupère les données depuis l'API Vélib'"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        stations_count = len(data.get("data", {}).get("stations", []))
        print(f"✓ {data_type} récupérées ({stations_count} stations)")
        return data
    except requests.RequestException as e:
        print(f"✗ Erreur récupération {data_type}: {e}")
        return None

def save_to_mongodb(db, data, collection_name, data_type):
    """Insertion dans MongoDB avec timestamp et historique"""
    if not data or "data" not in data:
        print(f"⚠ Données {data_type} invalides")
        return False

    collection = db[collection_name]
    timestamp = datetime.utcnow()
    stations = data["data"]["stations"]

    for station in stations:
        station["timestamp"] = timestamp
        station["last_updated_api"] = data.get("last_updated", timestamp)

    if stations:
        try:
            result = collection.insert_many(stations)
            print(f"✓ {len(result.inserted_ids)} enregistrements {data_type} insérés à {timestamp}")
            return True
        except errors.PyMongoError as e:
            print(f"✗ Erreur insertion {data_type}: {e}")
            return False
    else:
        print(f"⚠ Aucune station à insérer pour {data_type}")
        return False

# -------------------------------
# SCRIPT PRINCIPAL
# -------------------------------
def main():
    print("=== Démarrage synchronisation Vélib' → MongoDB ===\n")
    
    client = connect_mongodb(MONGO_URI)
    if not client:
        return

    db = client[DB_NAME]

    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"--- Itération #{iteration} ---")
            
            info_data = fetch_velib_data(STATION_INFO_URL, "Informations stations")
            if info_data:
                save_to_mongodb(db, info_data, COLLECTION_INFO, "informations")

            status_data = fetch_velib_data(STATION_STATUS_URL, "Statut stations")
            if status_data:
                save_to_mongodb(db, status_data, COLLECTION_STATUS, "statuts")

            print(f"⏳ Prochaine mise à jour dans {UPDATE_INTERVAL} secondes...\n")
            time.sleep(UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print("\n=== Arrêt du programme ===")
    finally:
        client.close()
        print("Connexion MongoDB fermée")

# -------------------------------
# LANCEMENT
# -------------------------------
if __name__ == "__main__":
    main()

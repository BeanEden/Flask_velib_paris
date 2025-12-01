import requests
import time
from datetime import datetime
from pymongo import MongoClient, errors
import os
import sys

# -------------------------------
# CONFIGURATION
# -------------------------------
STATION_INFO_URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_information.json"
STATION_STATUS_URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json"

# L'URI vient du docker-compose (mongodb://mongos:27017/velib)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/velib")

# CORRECTION 1 : Alignement avec le script mongo-setup.sh
DB_NAME = "velib" 

# CORRECTION 2 : Alignement avec la collection shardée
COLLECTION_INFO = "stations"
COLLECTION_STATUS = "status"

UPDATE_INTERVAL = 3600  # 1 heure
MAX_RETRIES = 5

# -------------------------------
# FONCTIONS
# -------------------------------
def connect_mongodb(uri, retries=MAX_RETRIES, wait=5):
    """Connexion à MongoDB avec retry"""
    for attempt in range(1, retries+1):
        try:
            # On se connecte
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            # On teste la commande ping
            client.admin.command("ping")
            print(f"✓ Connexion réussie au cluster MongoDB (via {uri})")
            return client
        except errors.ConnectionFailure as e:
            print(f"⚠ MongoDB non dispo (Tentative {attempt}/{retries})...")
            time.sleep(wait)
    
    print("✗ ERREUR CRITIQUE : Impossible de joindre le Mongos.")
    return None

def fetch_velib_data(url, data_type):
    """Récupère les données depuis l'API Vélib'"""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Petite sécurité : vérifie que 'data' existe
        stations = data.get("data", {}).get("stations", [])
        print(f"✓ API : {len(stations)} {data_type} téléchargées.")
        return data
    except requests.RequestException as e:
        print(f"✗ Erreur API ({data_type}): {e}")
        return None

def save_to_mongodb(db, data, collection_name, data_type):
    """Insertion dans MongoDB"""
    if not data or "data" not in data or "stations" not in data["data"]:
        print(f"⚠ Données {data_type} vides ou malformées.")
        return False

    collection = db[collection_name]
    timestamp = datetime.utcnow()
    stations = data["data"]["stations"]

    # Préparation des données
    for station in stations:
        station["scrape_timestamp"] = timestamp
        station["api_last_updated"] = data.get("last_updated")
        
        # Sécurité pour le Sharding : on s'assure que station_id existe
        # (L'API Velib utilise souvent 'station_id' ou 'stationCode')
        if "station_id" not in station and "stationCode" in station:
             station["station_id"] = station["stationCode"]

    if stations:
        try:
            # Insert Many est très performant pour du chargement en masse
            result = collection.insert_many(stations)
            print(f"💾 DB : {len(result.inserted_ids)} documents insérés dans '{DB_NAME}.{collection_name}'.")
            return True
        except errors.PyMongoError as e:
            print(f"✗ Erreur Mongo ({data_type}): {e}")
            return False
    return False

# -------------------------------
# MAIN
# -------------------------------
def main():
    # Force le flush pour voir les logs dans Docker instantanément
    sys.stdout.reconfigure(line_buffering=True)
    
    print("=== SCRAPER VÉLIB DÉMARRÉ ===")
    print(f"Cible : {MONGO_URI} | DB : {DB_NAME}")

    client = connect_mongodb(MONGO_URI)
    if not client:
        exit(1)

    db = client[DB_NAME]

    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"\n--- Cycle #{iteration} : {datetime.now().strftime('%H:%M:%S')} ---")
            
            # 1. Infos statiques (Nom, Lat, Lon)
            # Note: Idéalement on ne devrait pas insérer ça en boucle car ça change peu,
            # mais pour ce TP c'est très bien (ça génère du volume).
            info_data = fetch_velib_data(STATION_INFO_URL, "stations")
            if info_data:
                save_to_mongodb(db, info_data, COLLECTION_INFO, "stations")

            # 2. Status dynamique (Vélos dispos)
            status_data = fetch_velib_data(STATION_STATUS_URL, "status")
            if status_data:
                save_to_mongodb(db, status_data, COLLECTION_STATUS, "status")

            print(f"💤 Pause de {UPDATE_INTERVAL} secondes...")
            time.sleep(UPDATE_INTERVAL)

    except KeyboardInterrupt:
        print("\n=== Arrêt demandé ===")
    finally:
        client.close()
        print("Bye.")

if __name__ == "__main__":
    main()
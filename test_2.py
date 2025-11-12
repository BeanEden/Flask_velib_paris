import requests
import time
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

# Configuration
STATION_INFO_URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_information.json"
STATION_STATUS_URL = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json"
MONGO_URI = "mongodb://localhost:27017/"  # À adapter selon votre configuration
DB_NAME = "velib_data"
COLLECTION_INFO = "station"
COLLECTION_STATUS = "status"
UPDATE_INTERVAL = 60  # secondes

def connect_mongodb():
    """Connexion à MongoDB"""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Test de la connexion
        client.admin.command('ping')
        print(f"✓ Connexion MongoDB établie")
        return client
    except ConnectionFailure as e:
        print(f"✗ Erreur de connexion MongoDB: {e}")
        return None

def fetch_velib_data(url, data_type):
    """Récupère les données de l'API Vélib'"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        stations_count = len(data.get('data', {}).get('stations', []))
        print(f"✓ {data_type} récupérées: {stations_count} stations")
        return data
    except requests.exceptions.RequestException as e:
        print(f"✗ Erreur lors de la récupération {data_type}: {e}")
        return None

def save_to_mongodb(db, data, collection_name, data_type):
    """Sauvegarde les données dans MongoDB avec historique complet"""
    if not data or 'data' not in data:
        print(f"✗ Données {data_type} invalides")
        return False
    
    try:
        collection = db[collection_name]
        stations = data['data']['stations']
        
        # Ajout d'un timestamp à chaque enregistrement
        timestamp = datetime.utcnow()
        for station in stations:
            station['timestamp'] = timestamp
            station['last_updated_api'] = data.get('last_updated', timestamp)
        
        # Insertion pour garder l'historique complet
        if stations:
            result = collection.insert_many(stations)
            print(f"✓ {len(result.inserted_ids)} enregistrements {data_type} insérés à {timestamp.strftime('%H:%M:%S')}")
            return True
        else:
            print(f"⚠ Aucune station à insérer pour {data_type}")
            return False
            
    except OperationFailure as e:
        print(f"✗ Erreur lors de la sauvegarde {data_type}: {e}")
        return False

def main():
    """Fonction principale"""
    print("=== Démarrage du synchroniseur Vélib' → MongoDB ===\n")
    
    # Connexion à MongoDB
    client = connect_mongodb()
    if not client:
        print("Impossible de se connecter à MongoDB. Arrêt du programme.")
        return
    
    db = client[DB_NAME]
    
    print(f"Base de données: {DB_NAME}")
    print(f"Collections:")
    print(f"  - {COLLECTION_INFO} (informations des stations)")
    print(f"  - {COLLECTION_STATUS} (statut des stations)")
    print(f"Intervalle de mise à jour: {UPDATE_INTERVAL} secondes")
    print(f"Mode: Historique complet\n")
    print("Appuyez sur Ctrl+C pour arrêter\n")
    
    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"--- Itération #{iteration} ---")
            
            # Récupération et sauvegarde des informations de stations
            info_data = fetch_velib_data(STATION_INFO_URL, "Informations stations")
            if info_data:
                save_to_mongodb(db, info_data, COLLECTION_INFO, "informations")
            
            # Récupération et sauvegarde du statut des stations
            status_data = fetch_velib_data(STATION_STATUS_URL, "Statut stations")
            if status_data:
                save_to_mongodb(db, status_data, COLLECTION_STATUS, "statuts")
            
            # Attente avant la prochaine mise à jour
            print(f"⏳ Prochaine mise à jour dans {UPDATE_INTERVAL} secondes...\n")
            time.sleep(UPDATE_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n=== Arrêt du programme ===")
    finally:
        client.close()
        print("Connexion MongoDB fermée")

if __name__ == "__main__":
    main()

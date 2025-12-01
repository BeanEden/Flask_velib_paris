import os
from flask import Flask, render_template, jsonify
from pymongo import MongoClient
from datetime import datetime, timezone

app = Flask(__name__)

# --- CONFIGURATION ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongos:27017/velib")
client = MongoClient(MONGO_URI)
db = client['velib']

# --- OPTIMISATION INDEX ---
try:
    # Index composite pour accélérer le lookup + sort
    db.status.create_index([("station_id", 1), ("scrape_timestamp", -1)])
    print("Index sur status créé/vérifié.")
except Exception as e:
    print(f"Warning: Impossible de créer l'index: {e}")

# --- ROUTE 1 : PAGE D'ACCUEIL (LA CARTE) ---
@app.route('/')
def index():
    return render_template('index.html')

# --- ROUTE 2 : API POUR LA CARTE (DONNÉES JSON) ---
@app.route('/api/map_data')
def api_map_data():
    """
    Cette route renvoie le JSON utilisé par Leaflet.
    Optimisation : 
    1. On ne récupère qu'une seule entrée par station (la plus récente).
    2. On fait un lookup optimisé pour ne récupérer que le dernier statut.
    """
    pipeline = [
        # 1. Dédoublonnage des stations (car le scraper insère en boucle)
        # On groupe par station_id et on garde les infos de la dernière entrée
        {
            "$sort": {"scrape_timestamp": -1} # Pour être sûr de prendre le dernier nom/lat/lon
        },
        {
            "$group": {
                "_id": "$station_id",
                "name": {"$first": "$name"},
                "lat": {"$first": "$lat"},
                "lon": {"$first": "$lon"}
            }
        },
        # 2. Lookup optimisé : on ne récupère QUE le dernier statut
        {
            "$lookup": {
                "from": "status",
                "let": {"sid": "$_id"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$station_id", "$$sid"]}}},
                    {"$sort": {"scrape_timestamp": -1}},
                    {"$limit": 1}
                ],
                "as": "latest_status_array"
            }
        },
        # 3. On met à plat le tableau (qui contient 0 ou 1 élément)
        {
            "$addFields": {
                "latest_status": {"$arrayElemAt": ["$latest_status_array", 0]}
            }
        },
        # 4. Projection finale
        {
            "$project": {
                "_id": 0,
                "station_id": "$_id", # On garde l'ID si besoin
                "name": 1,
                "lat": 1,
                "lon": 1,
                "bikes": "$latest_status.num_bikes_available",
                "docks": "$latest_status.num_docks_available"
            }
        }
    ]

    # On exécute
    try:
        data = list(db.stations.aggregate(pipeline))
        # Nettoyage des coordonnées nulles
        clean_data = [d for d in data if d.get('lat') and d.get('lon')]
        return jsonify(clean_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- TES ROUTES EXISTANTES (MONITORING & LISTE) ---

def get_shard_stats():
    try:
        stats = db.command("collStats", "stations")
        shards_data = stats.get('shards', {})
        labels = []
        counts = []
        sizes = []
        for shard_name, shard_info in shards_data.items():
            labels.append(shard_name)
            counts.append(shard_info.get('count', 0))
            sizes.append(round(shard_info.get('size', 0) / 1024, 2)) 
        return {
            "labels": labels, "counts": counts, "sizes": sizes,
            "total_count": stats.get('count', 0),
            "total_size": round(stats.get('size', 0) / 1024, 2),
            "avg_obj_size": stats.get('avgObjSize', 0)
        }
    except Exception as e:
        print(f"Erreur stats shards: {e}")
        return {"labels": [], "counts": [], "sizes": [], "total_count": 0, "total_size": 0, "avg_obj_size": 0}

@app.route('/monitoring/')
def dashboard():
    shard_stats = get_shard_stats()
    last_entry = db.status.find_one(sort=[("_id", -1)]) # Tri par ID plus fiable
    
    time_since_update = "Jamais"
    last_update_str = "Aucune donnée"

    if last_entry:
        # On essaie de trouver une date valide
        last_update = last_entry.get('scrape_timestamp') or last_entry.get('timestamp') or last_entry['_id'].generation_time
        
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
            
        now_utc = datetime.now(timezone.utc)
        delta = now_utc - last_update
        minutes = int(delta.total_seconds() / 60)
        
        time_since_update = f"il y a {minutes} min"
        last_update_str = last_update.strftime("%Y-%m-%d %H:%M:%S UTC")

    total_stations = db.stations.count_documents({})
    total_status_logs = db.status.count_documents({})

    return render_template(
        'monitor.html',
        shard_stats=shard_stats,
        last_update=last_update_str,
        time_since_update=time_since_update,
        total_stations=total_stations,
        total_status_logs=total_status_logs
    )

@app.route('/velib_list/')
def velib_list():
    pipeline = [
        {"$limit": 50},
        {
            "$lookup": {
                "from": "status",
                "localField": "station_id",
                "foreignField": "station_id",
                "as": "status_info"
            }
        },
        {
            "$addFields": {
                "latest_status": {"$last": "$status_info"}
            }
        }
    ]
    stations = list(db.stations.aggregate(pipeline))
    return render_template('velib_list.html', stations=stations)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
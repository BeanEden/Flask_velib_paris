import os
from flask import Flask, render_template
from pymongo import MongoClient
from datetime import datetime, timezone

app = Flask(__name__)

# Configuration (identique au scraper)
# On passe par le routeur (mongos) pour avoir accès à tout le cluster
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongos:27017/velib")
client = MongoClient(MONGO_URI)
db = client['velib']  # La base qu'on a créée ensemble


def get_shard_stats():
    """
    Exécute la commande administrative 'collStats' pour obtenir
    la répartition précise des données sur les shards.
    """
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
            "labels": labels,
            "counts": counts,
            "sizes": sizes,
            "total_count": stats.get('count', 0),
            "total_size": round(stats.get('size', 0) / 1024, 2),
            "avg_obj_size": stats.get('avgObjSize', 0)
        }
    except Exception as e:
        print(f"Erreur stats shards: {e}")
        return {
            "labels": [], "counts": [], "sizes": [], 
            "total_count": 0, "total_size": 0, "avg_obj_size": 0
        }


@app.route('/monitoring/')
def dashboard():
    # 1. Récupérer les stats de Sharding
    shard_stats = get_shard_stats()

    # 2. Récupérer la dernière date de mise à jour
    last_entry = db.status.find_one(sort=[("_id", -1)])
    
    # --- CORRECTION DE LA GESTION DES DATES ---
    time_since_update = "Jamais"
    last_update_str = "Aucune donnée"

    if last_entry and 'timestamp' in last_entry:
        last_update = last_entry['timestamp']
        
        # On s'assure que la date venant de Mongo est "aware" (a un timezone)
        # Si elle est naive (pas de tz), on lui colle UTC
        if last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=timezone.utc)
            
        # On récupère l'heure actuelle en UTC "aware" (la nouvelle façon de faire en Python 3.12+)
        now_utc = datetime.now(timezone.utc)
        
        # Maintenant on peut soustraire sans erreur
        delta = now_utc - last_update
        minutes = int(delta.total_seconds() / 60)
        
        time_since_update = f"il y a {minutes} min"
        last_update_str = last_update.strftime("%Y-%m-%d %H:%M:%S UTC")

    # 3. Compteurs globaux
    total_stations = db.stations.count_documents({})
    total_status_logs = db.status.count_documents({})

    return render_template(
        'monitor.html',
        shard_stats=shard_stats,
        last_update=last_update_str, # On passe une string formatée pour éviter les soucis dans le HTML
        time_since_update=time_since_update,
        total_stations=total_stations,
        total_status_logs=total_status_logs
    )


@app.route('/velib_list/')
def velib_list():
    # Pipeline d'agrégation pour récupérer les stations ET leur dernier statut
    # C'est l'équivalent d'un JOIN en SQL
    pipeline = [
        {"$limit": 50},  # On en prend juste 50 pour l'exemple (évite de charger 1500 lignes)
        {
            "$lookup": {
                "from": "status",             # Table à joindre
                "localField": "station_id",   # Clé dans 'stations'
                "foreignField": "station_id", # Clé dans 'status'
                "as": "status_info"           # Nom du champ résultat
            }
        },
        # Le lookup renvoie une liste, on prend le dernier élément (le plus récent)
        {
            "$addFields": {
                "latest_status": {"$last": "$status_info"}
            }
        }
    ]

    # Exécution de la requête sur le cluster
    stations = list(db.stations.aggregate(pipeline))

    return render_template('velib_list.html', stations=stations)

if __name__ == "__main__":
    # Host 0.0.0.0 est obligatoire pour que Docker expose le port
    app.run(host='0.0.0.0', port=5000, debug=True)
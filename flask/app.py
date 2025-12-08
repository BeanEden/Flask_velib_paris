import os
import json
from flask import Flask, render_template, jsonify, request, send_from_directory
from pymongo import MongoClient
from datetime import datetime, timezone
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env (pour le dev local)
load_dotenv()


app = Flask(__name__)

# --- CONFIGURATION ---
# --- CONFIGURATION ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongos:27017/velib")
MONGO_URI_CLOUD = os.getenv("MONGO_URI_CLOUD") # Ajout pour la météo si stockée ailleurs

# Connexion principale (Velib)
client = MongoClient(MONGO_URI)
db = client['velib']



# Connexion Météo (si Cloud spécifié, sinon local/principal)
if MONGO_URI_CLOUD:
    try:
        client_weather = MongoClient(MONGO_URI_CLOUD)
        weather_db = client_weather['Meteo'] # Correction: Base 'Meteo'
        col_weather_current = weather_db['meteo_current']
        col_weather_forecast = weather_db['meteo_forecast']
        print("Connecté à MongoDB Cloud pour la Météo.")
    except Exception as e:
        print(f"Erreur connexion Cloud Météo: {e}, fallback sur local.")
        col_weather_current = db['meteo_current']
        col_weather_forecast = db['meteo_forecast']
else:
    col_weather_current = db['meteo_current']
    col_weather_forecast = db['meteo_forecast']
    
def get_weather_description(code):
    table = {
        0: "Ciel clair", 1: "Principalement clair", 2: "Partiellement nuageux", 3: "Couvert",
        45: "Brouillard", 48: "Brouillard givrant", 51: "Bruine légère", 53: "Bruine modérée",
        55: "Bruine dense", 56: "Bruine verglaçante légère", 57: "Bruine verglaçante dense",
        61: "Pluie faible", 63: "Pluie modérée", 65: "Pluie forte", 66: "Pluie verglaçante légère",
        67: "Pluie verglaçante forte", 71: "Faibles chutes de neige", 73: "Chutes de neige modérées",
        75: "Fortes chutes de neige", 77: "Grains de neige", 80: "Averses faibles", 81: "Averses modérées",
        82: "Averses fortes", 85: "Averses de neige faibles", 86: "Averses de neige fortes",
        95: "Orage faible/modéré", 96: "Orage avec grêle", 99: "Orage violent avec grêle",
    }
    return table.get(code, "Code inconnu")

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

# --- ROUTE 3 : STATISTIQUES HORAIRES ---
from flask import request

@app.route('/api/hourly_stats', methods=['POST'])
def api_hourly_stats():
    """
    Calcule la moyenne des vélos disponibles par heure pour une liste de stations donnée.
    """
    try:
        req_data = request.get_json()
        station_ids = req_data.get('station_ids', [])
        
        if not station_ids:
            return jsonify([])

        # 1. Calcul de la capacité totale pour ces stations
        # On récupère le dernier statut connu pour chaque station demandée
        capacity_pipeline = [
            {"$match": {"station_id": {"$in": station_ids}}},
            {"$sort": {"scrape_timestamp": -1}},
            {"$group": {
                "_id": "$station_id",
                "last_bikes": {"$first": "$num_bikes_available"},
                "last_docks": {"$first": "$num_docks_available"}
            }},
            {"$project": {
                "capacity": {"$add": ["$last_bikes", "$last_docks"]}
            }},
            {"$group": {
                "_id": None,
                "total_capacity": {"$sum": "$capacity"}
            }}
        ]
        
        capacity_res = list(db.status.aggregate(capacity_pipeline))
        total_capacity = capacity_res[0]['total_capacity'] if capacity_res else 0

        pipeline = [
            # 1. Filtrer sur les stations visibles
            {
                "$match": {
                    "station_id": {"$in": station_ids}
                }
            },
            # 2. Extraire l'heure du timestamp
            {
                "$project": {
                    "hour": {"$hour": "$scrape_timestamp"},
                    "bikes": "$num_bikes_available"
                }
            },
            # 3. Grouper par heure et calculer la moyenne
            {
                "$group": {
                    "_id": "$hour",
                    "avg_bikes": {"$avg": "$bikes"}
                }
            },
            # 4. Trier par heure (0h -> 23h)
            {
                "$sort": {"_id": 1}
            }
        ]

        stats = list(db.status.aggregate(pipeline))
        
        # Formater pour le frontend : tableau de 24 valeurs (une par heure)
        # On met None si pas de données pour ne pas fausser la moyenne
        hourly_data = [None] * 24
        for s in stats:
            hour = s['_id']
            avg = s.get('avg_bikes')
            
            if hour is not None and 0 <= hour < 24:
                hourly_data[hour] = round(avg, 1) if avg is not None else None
                
        return jsonify({
            "data": hourly_data,
            "capacity": total_capacity
        })

    except Exception as e:
        print(f"Error stats: {e}")
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
    
    # Stats Météo
    total_weather_logs = col_weather_current.count_documents({})
    total_forecasts = col_weather_forecast.count_documents({})
    
    last_weather_entry = col_weather_current.find_one(sort=[("scrape_timestamp", -1)])
    weather_last_update_str = "Aucune donnée"
    if last_weather_entry:
         lwu = last_weather_entry.get('scrape_timestamp')
         if lwu:
             if lwu.tzinfo is None: lwu = lwu.replace(tzinfo=timezone.utc)
             weather_last_update_str = lwu.strftime("%Y-%m-%d %H:%M:%S UTC")

    return render_template(
        'monitor.html',
        shard_stats=shard_stats,
        last_update=last_update_str,
        time_since_update=time_since_update,
        total_stations=total_stations,
        total_status_logs=total_status_logs,
        total_weather_logs=total_weather_logs,
        total_forecasts=total_forecasts,
        weather_last_update=weather_last_update_str
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

# --- ROUTE 4 : RECHERCHE D'ITINÉRAIRE ---
import math

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calcule la distance en mètres entre deux points (Haversine).
    """
    R = 6371000  # Rayon de la Terre en mètres
    phi1 = lat1 * math.pi / 180
    phi2 = lat2 * math.pi / 180
    delta_phi = (lat2 - lat1) * math.pi / 180
    delta_lambda = (lon2 - lon1) * math.pi / 180

    a = math.sin(delta_phi / 2) * math.sin(delta_phi / 2) + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2) * math.sin(delta_lambda / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

@app.route('/api/find_route', methods=['POST'])
def api_find_route():
    """
    Trouve la station de départ (avec vélos) et d'arrivée (avec places) les plus proches.
    Gère le temps réel ou prévisionnel selon l'heure demandée.
    """
    try:
        data = request.get_json()
        start_lat = float(data.get('start_lat'))
        start_lon = float(data.get('start_lon'))
        end_lat = float(data.get('end_lat'))
        end_lon = float(data.get('end_lon'))
        time_str = data.get('time') # ISO string

        # 1. Analyse de l'heure
        req_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc) if req_time.tzinfo else datetime.now()
        
        # Si l'heure demandée est dans le passé ou dans moins d'1h, on considère "Maintenant"
        diff_hours = (req_time - now).total_seconds() / 3600
        is_realtime = diff_hours < 1

        print(f"Route request: Realtime={is_realtime}, Time={req_time}")

        # 2. Récupération de toutes les stations (Nom, Lat, Lon)
        # On utilise le même pipeline que map_data pour avoir les infos de base
        # Mais on a besoin de filtrer ensuite.
        # Pour faire simple et robuste : on récupère tout et on trie en Python.
        
        # Pipeline simplifié pour avoir juste les infos statiques + dernier status
        pipeline = [
            {"$sort": {"scrape_timestamp": -1}},
            {"$group": {
                "_id": "$station_id",
                "name": {"$first": "$name"},
                "lat": {"$first": "$lat"},
                "lon": {"$first": "$lon"}
            }},
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
            {"$addFields": {"latest_status": {"$arrayElemAt": ["$latest_status_array", 0]}}}
        ]
        
        stations = list(db.stations.aggregate(pipeline))
        
        candidates_start = []
        candidates_end = []

        # 3. Filtrage et Calcul de distance
        for s in stations:
            if not s.get('lat') or not s.get('lon'):
                continue
                
            dist_start = calculate_distance(start_lat, start_lon, s['lat'], s['lon'])
            dist_end = calculate_distance(end_lat, end_lon, s['lat'], s['lon'])
            
            # Critères de disponibilité
            bikes = 0
            docks = 0
            
            if is_realtime:
                # Mode Temps Réel
                ls = s.get('latest_status', {})
                if ls:
                    bikes = ls.get('num_bikes_available', 0)
                    docks = ls.get('num_docks_available', 0)
            else:
                # Mode Prévisionnel (Moyenne historique pour l'heure demandée)
                # On ne fait pas la requête ici pour ne pas ralentir
                # On le fera seulement pour les candidats proches
                pass 

            # On ajoute aux candidats avec la distance
            # Pour le prévisionnel, on fera le check après le tri par distance pour minimiser les requêtes DB
            s['dist_start'] = dist_start
            s['dist_end'] = dist_end
            s['realtime_bikes'] = bikes
            s['realtime_docks'] = docks
            
            candidates_start.append(s)
            candidates_end.append(s)

        # 4. Tri et Sélection
        candidates_start.sort(key=lambda x: x['dist_start'])
        candidates_end.sort(key=lambda x: x['dist_end'])

        best_start = None
        best_end = None

        # Recherche du meilleur départ
        for cand in candidates_start[:10]: # On regarde les 10 plus proches
            if is_realtime:
                if cand['realtime_bikes'] > 0:
                    best_start = cand
                    break
            else:
                # Check historique
                avg_bikes = get_historical_avg(cand['_id'], req_time.hour, 'bikes')
                if avg_bikes >= 1:
                    best_start = cand
                    break
        
        # Recherche de la meilleure arrivée
        for cand in candidates_end[:10]:
            if is_realtime:
                if cand['realtime_docks'] > 0:
                    best_end = cand
                    break
            else:
                # Check historique
                avg_docks = get_historical_avg(cand['_id'], req_time.hour, 'docks')
                if avg_docks >= 1:
                    best_end = cand
                    break

        # Fallback si rien trouvé (on prend le plus proche même si vide, ou on gère l'erreur)
        if not best_start: best_start = candidates_start[0] if candidates_start else None
        if not best_end: best_end = candidates_end[0] if candidates_end else None

        return jsonify({
            "start_station": format_station_response(best_start, "start"),
            "end_station": format_station_response(best_end, "end")
        })

    except Exception as e:
        print(f"Error find_route: {e}")
        return jsonify({"error": str(e)}), 500

def get_historical_avg(station_id, hour, field_type):
    """
    Calcule la moyenne historique pour une station et une heure donnée.
    field_type: 'bikes' ou 'docks'
    """
    field_map = {
        'bikes': 'num_bikes_available',
        'docks': 'num_docks_available'
    }
    pipeline = [
        {"$match": {"station_id": station_id}},
        {"$project": {"hour": {"$hour": "$scrape_timestamp"}, "val": f"${field_map[field_type]}"}},
        {"$match": {"hour": hour}},
        {"$group": {"_id": None, "avg": {"$avg": "$val"}}}
    ]
    res = list(db.status.aggregate(pipeline))
    if res:
        return res[0]['avg']
    return 0

def format_station_response(station, type_):
    if not station: return None
    return {
        "station_id": station['_id'],
        "name": station['name'],
        "lat": station['lat'],
        "lon": station['lon'],
        "distance": round(station[f'dist_{type_}'], 0), # Mètres
        "bikes": station.get('realtime_bikes'), # Peut être 0 ou None si prévisionnel
        "docks": station.get('realtime_docks')
    }

# --- ROUTE 5 : MÉTÉO & PRÉVISIONS ---

@app.route('/forecast')
def forecast_page():
    return render_template('forecast.html')

@app.route('/api/weather')
def api_weather():
    """
    Renvoie la dernière météo enregistrée dans MongoDB (meteo_current).
    """
    try:
        # On récupère le dernier document inséré
        weather_data = col_weather_current.find_one(sort=[("scrape_timestamp", -1)], projection={"_id": 0})
        if not weather_data:
            return jsonify({"error": "No weather data found"}), 404
            
        # Enrichir avec description
        code = weather_data.get('weathercode')
        weather_data['description'] = get_weather_description(code)
        
        return jsonify(weather_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import joblib
import pandas as pd
import numpy as np

# Load Model
MODEL_PATH = "/models/velib_model.pkl"
try:
    model = joblib.load(MODEL_PATH)
    print(f"Modèle chargé depuis {MODEL_PATH}")
except Exception as e:
    print(f"Erreur chargement modèle: {e}")
    model = None

@app.route('/model', strict_slashes=False)
def model_dashboard():
    print("Accessing /model dashboard")
    metrics = {}
    try:
        with open("/models/metrics.json", "r") as f:
            metrics = json.load(f)
            print(f"Loaded metrics: {metrics}")
    except Exception as e:
        print(f"Error loading metrics: {e}")
        metrics = {"error": "Modèle non entraîné ou fichier manquant.", "raw_error": str(e)}

    return render_template('model.html', metrics=metrics)

@app.route('/models_static/<path:filename>')
def models_static(filename):
    return send_from_directory('/models', filename)

@app.route('/api/forecast_stats', methods=['POST'])
def api_forecast_stats():
    """
    Renvoie les prévisions de disponibilité des vélos basées sur le modèle ML.
    Gère la spécificité par station en pondérant par la capacité.
    """
    try:
        req_data = request.get_json()
        station_id = req_data.get('station_id') # Optional specific station
        
        # 1. Fetch Station Capacity if specific station requested
        station_capacity = 30 # Default average capacity
        station_name = "Global"
        
        if station_id:
            try:
                # Try to get station capacity from latest status or static info
                # Here we fetch the latest status to get capacity = bikes + docks
                stat = db.status.find_one({"station_id": station_id}, sort=[("scrape_timestamp", -1)])
                if stat:
                    station_capacity = stat.get('num_bikes_available', 0) + stat.get('num_docks_available', 0)
                
                # Fetch Name
                st_info = db.stations.find_one({"_id": station_id})
                if st_info: station_name = st_info.get('name', 'Station')
            except Exception as e:
                print(f"Warning fetching station info: {e}")

        # 2. Récupérer les prévisions futures depuis meteo_forecast
        now = datetime.now()
        cursor = col_weather_forecast.find({
            "time": {"$gte": now.strftime("%Y-%m-%dT%H:00")}
        }).sort("time", 1).limit(48)
        
        forecast_items = list(cursor)
        predictions = []
        
        if forecast_items and model:
            # Prepare DataFrame for Model
            rows = []
            for item in forecast_items:
                t_str = item.get('time')
                dt = datetime.fromisoformat(t_str)
                
                row = {
                    'hour': dt.hour,
                    'day_of_week': dt.weekday(),
                    'temperature': item.get('temperature', 15),
                    'windspeed': item.get('windspeed', 10),
                    'weathercode': item.get('weathercode', 0),
                    # Meta info to keep for result
                    '_time': t_str,
                    '_desc': get_weather_description(item.get('weathercode', 0))
                }
                rows.append(row)
            
            df_pred = pd.DataFrame(rows)
            
            # Predict (Returns GLOBAL AVERAGE)
            features = ['hour', 'day_of_week', 'temperature', 'windspeed', 'weathercode']
            X = df_pred[features]
            y_pred = model.predict(X)
            
            # Scale Factor: (Station Capacity / Avg Capacity of ~30)
            # This makes big stations have big numbers, small stations have small numbers.
            # We assume the model was trained on an average station of capacity ~30.
            # If the model predicts 15 (50%), a 60-slot station should show 30.
            scale_factor = station_capacity / 30.0
            
            # Format results
            for i, row in enumerate(rows):
                # Ensure non-negative and round
                global_val = float(y_pred[i])
                scaled_val = max(0, round(global_val * scale_factor))
                
                # Clip to actual capacity if known
                if station_id:
                    scaled_val = min(scaled_val, station_capacity)
                
                predictions.append({
                    "time": row['_time'],
                    "temp": row['temperature'],
                    "wind": row['windspeed'],
                    "weather_description": row['_desc'],
                    "weather_code": row['weathercode'],
                    "predicted_bikes": scaled_val
                })
                
        else:
            # Fallback (Simulated or Error if critical)
            print("Fallback forecast (No model or No data)")
            for i in range(0, 24, 3): 
                future_time = now.replace(hour=i, minute=0, second=0, microsecond=0)
                if future_time < now: future_time = future_time.replace(day=future_time.day + 1)
                
                predictions.append({
                    "time": future_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "temp": 15,
                    "wind": 10,
                    "weather_description": "Données simulées (Modèle HS)",
                    "predicted_bikes": 10
                })
                
        return jsonify({
            "predictions": predictions,
            "station_id": station_id,
            "station_capacity": station_capacity
        })

    except Exception as e:
        print(f"Error forecast stats: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
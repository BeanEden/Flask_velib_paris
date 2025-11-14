from flask import Flask, render_template, request, jsonify
from math import radians, cos, sin, asin, sqrt
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId
import os


app = Flask(__name__)

# MongoDB
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "velib_data"
COLLECTION_INFO = "station"
COLLECTION_STATUS = "status"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]


def fix_json(doc):
    """Convertit ObjectId et datetime en string pour JSON"""
    doc = dict(doc)
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            doc[key] = str(value)
        elif isinstance(value, datetime):
            doc[key] = value.isoformat()
        elif isinstance(value, list):
            doc[key] = [fix_json(v) if isinstance(v, dict) else v for v in value]
        elif isinstance(value, dict):
            doc[key] = fix_json(value)
    return doc

def haversine(lat1, lon1, lat2, lon2):
    """Calcule la distance en km entre deux points GPS"""
    # convert degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    c = 2*asin(sqrt(a))
    km = 6371 * c
    return km

@app.route("/nearest_stations")
def nearest_stations():
    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))
    stations_info = list(db[COLLECTION_INFO].find({}))

    # Harmonisation et fix JSON
    result = []
    for station in stations_info:
        merged = fix_json(station)
        merged["lat"] = float(merged.get("lat") or merged.get("latitude") or 0)
        merged["lon"] = float(merged.get("lon") or merged.get("longitude") or 0)
        merged["num_bikes_available"] = merged.get("num_bikes_available") or merged.get("numBikesAvailable") or 0
        merged["num_docks_available"] = merged.get("num_docks_available") or merged.get("numDocksAvailable") or 0
        merged["distance"] = haversine(lat, lon, merged["lat"], merged["lon"])
        result.append(merged)

    # Trier par distance et ne garder que les 3 premières
    result.sort(key=lambda s: s["distance"])
    nearest = result[:3]

    # Optionnel : ne garder que les champs utiles pour le front
    nearest_info = [
        {
            "name": s["name"],
            "distance": s["distance"],
            "lat": s["lat"],
            "lon": s["lon"],
            "num_bikes_available": s["num_bikes_available"],
            "num_docks_available": s["num_docks_available"],
            "capacity": s.get("capacity", 0)
        }
        for s in nearest
    ]

    return jsonify(nearest_info)


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/stations")
def get_stations():
    stations_info = list(db[COLLECTION_INFO].find({}))
    
    # On récupère les statuts les plus récents
    stations_status = {}
    for s in db[COLLECTION_STATUS].find().sort("timestamp", -1):
        if s["station_id"] not in stations_status:
            stations_status[s["station_id"]] = s  # garder uniquement le dernier

    result = []
    for station in stations_info:
        station_id = station["station_id"]
        latest_status = stations_status.get(station_id, {})
        merged = {**station, **latest_status}

        # Harmoniser les noms
        merged["lat"] = float(merged.get("lat") or merged.get("latitude") or 0)
        merged["lon"] = float(merged.get("lon") or merged.get("longitude") or 0)
        merged["num_bikes_available"] = merged.get("num_bikes_available") or merged.get("numBikesAvailable") or 0
        merged["num_docks_available"] = merged.get("num_docks_available") or merged.get("numDocksAvailable") or 0

        # Convertir ObjectId et nested dicts
        merged = fix_json(merged)

        result.append(merged)

    # Filtrage multi-critères
    min_bikes = int(request.args.get("min_bikes", 0))
    min_docks = int(request.args.get("min_docks", 0))
    arrondissement = request.args.get("arrondissement", "").lower().strip()
    result = [
    s for s in result
    if s.get("num_bikes_available", 0) >= min_bikes
    and s.get("num_docks_available", 0) >= min_docks
    and (arrondissement in s.get("name", "").lower() if arrondissement else True)
    ]

    
    # Tri multi-critères
    sort_by = request.args.get("sort_by", "name")
    order = request.args.get("order", "asc")
    reverse = order == "desc"
    result.sort(key=lambda s: s.get(sort_by, 0) or 0, reverse=reverse)

    return jsonify(result)

@app.route("/station_chart")
def station_chart():
    station_id = request.args.get("station_id")
    mode = request.args.get("mode", "bikes")  # 'bikes' ou 'docks'

    # Récupération de la station
    station = db[COLLECTION_INFO].find_one({"station_id": station_id})
    if not station:
        return jsonify([])

    # Récupérer le dernier status + historique si nécessaire
    history = list(db[COLLECTION_STATUS].find({"station_id": station_id}).sort("timestamp", -1).limit(100))

    # Calculer moyenne par heure
    hourly = {}
    for h in history:
        hour = h["timestamp"].hour if isinstance(h["timestamp"], datetime) else datetime.fromisoformat(h["timestamp"]).hour
        value = h.get("num_bikes_available" if mode=="bikes" else "num_docks_available", 0)
        hourly.setdefault(hour, []).append(value)

    chart_data = [{"hour": h, "avg": sum(vals)/len(vals)} for h, vals in hourly.items()]
    chart_data = sorted(chart_data, key=lambda x: x["hour"])
    return jsonify(chart_data)


@app.route("/hourly_data")
def hourly_data():
    """
    Retourne les moyennes horaires pour toutes les stations ou une station spécifique.
    """
    mode = request.args.get("mode", "bikes")
    station_id = request.args.get("station_id")

    # Récupération des statuts
    statuses = list(db[COLLECTION_STATUS].find({}))
    if station_id:
        statuses = [s for s in statuses if s["station_id"] == station_id]

    # Calcul par heure
    hourly = {}
    for s in statuses:
        hour = s["timestamp"].hour
        value = s.get("num_bikes_available" if mode == "bikes" else "num_docks_available", 0)
        hourly.setdefault(hour, []).append(value)

    # Moyenne par heure
    data = [{"hour": h, "avg": sum(vals)/len(vals)} for h, vals in sorted(hourly.items())]

    return jsonify(data)



if __name__ == "__main__":
    from os import getenv
    app.run(host="0.0.0.0", port=int(getenv("PORT", 5000)), debug=True)


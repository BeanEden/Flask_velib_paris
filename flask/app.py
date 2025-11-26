import os, datetime, json
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient
import requests
from joblib import load
from geopy.distance import geodesic

MONGO_URI = os.getenv("MONGO_URI","mongodb://localhost:27017/velib")
client = MongoClient(MONGO_URI)
db = client.velib
stations = db.stations

app = Flask(__name__)

# helper: get weather (current) via OpenWeatherMap
def get_weather(lat, lon):
    key = os.getenv("OPENWEATHER_API_KEY")
    if not key: return {}
    r = requests.get("https://api.openweathermap.org/data/2.5/weather",
                     params={"lat":lat,"lon":lon,"appid":key,"units":"metric"})
    return r.json()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ingest/station", methods=["POST"])
def ingest_station():
    payload = request.get_json()
    # payload example: { "station_id":123, "capacity":20, "lat":..., "lon":..., "ts":"2025-11-17T12:00:00Z", "available":5 }
    payload["ts"] = payload.get("ts", datetime.datetime.utcnow().isoformat())
    stations.insert_one(payload)
    return jsonify({"status":"ok"}), 201

@app.route("/predict", methods=["GET"])
def predict():
    # query params: station_id, date (YYYY-MM-DD), hour (0-23)
    station_id = int(request.args["station_id"])
    date = request.args.get("date")
    hour = int(request.args.get("hour", datetime.datetime.utcnow().hour))
    # For demo: load a pre-trained model if exists
    try:
        model = load("model.joblib")
    except:
        return jsonify({"error":"model not available"}), 400
    # build feature vector minimal for demo (in real: comprehensive features)
    # fetch station metadata
    st = stations.find_one({"station_id":station_id}, sort=[("ts",-1)])
    if not st:
        return jsonify({"error":"station not found"}), 404
    # naive features
    feat = {
      "heure": hour,
      "jour_semaine": datetime.datetime.fromisoformat(date).weekday() if date else datetime.datetime.utcnow().weekday(),
      "capacite": st.get("capacity", st.get("capacite",20)),
      "lat": st.get("lat") or st.get("latitude"),
      "lon": st.get("lon") or st.get("longitude")
    }
    # convert to vector (must match training)
    X = [[feat["heure"], feat["jour_semaine"], feat["capacite"]]]
    pred = model.predict(X)[0]
    return jsonify({"station_id": station_id, "pred": float(pred)})

@app.route("/recommend", methods=["POST"])
def recommend():
    data = request.get_json()
    user = tuple(data["user"])  # [lat,lon]
    dest = tuple(data["dest"])
    radius = data.get("radius_m", 500)
    # find candidate stations within radius (approx)
    candidates = []
    for s in stations.find():
        s_loc = (s.get("lat") or s.get("latitude"), s.get("lon") or s.get("longitude"))
        if None in s_loc: continue
        dist = geodesic(user, s_loc).meters
        if dist <= radius:
            candidates.append((s, dist))
    if not candidates: return jsonify({"error":"no_station"}), 404
    # scoring simple: predicted availability (if model exists) else current available / capacity
    try:
        model = load("model.joblib")
    except:
        model = None
    scored = []
    for s, dist in candidates:
        if model:
            pred = model.predict([[datetime.datetime.utcnow().hour, datetime.datetime.utcnow().weekday(), s.get("capacity",20)]])[0]
            score_dispo = max(0, min(1, pred / s.get("capacity",20)))
        else:
            score_dispo = min(1, (s.get("available",0) / s.get("capacity",20)))
        score_prox = 1 - (dist / radius)
        score = 0.4*score_dispo + 0.3*score_prox
        scored.append((score, s, dist))
    scored.sort(reverse=True, key=lambda x: x[0])
    best = scored[0]
    return jsonify({
        "station": {
            "station_id": best[1]["station_id"],
            "name": best[1].get("name")
        },
        "walk_m": best[2],
        "score": best[0]
    })

@app.route("/stats/distribution")
def distribution():
    # simple: use admin command getShardDistribution via db.runCommand not available, so we show counts
    pipeline = [
        {"$group": {"_id":"$station_id", "count":{"$sum":1}}}
    ]
    total = stations.count_documents({})
    return jsonify({"total_docs": total})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


import gpxpy, gpxpy.gpx
@app.route("/export/gpx", methods=["POST"])
def export_gpx():
    route = request.get_json()["geojson"]  # list of [lat,lon]
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)
    seg = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(seg)
    for c in route:
        seg.points.append(gpxpy.gpx.GPXTrackPoint(c[0], c[1]))
    return gpx.to_xml(), 200, {'Content-Type':'application/gpx+xml'}

import os, time, requests
from pymongo import MongoClient
from datetime import datetime

MONGO_URI = os.getenv("MONGO_URI","mongodb://localhost:27017/velib")
OW_KEY = os.getenv("OPENWEATHER_API_KEY")
client = MongoClient(MONGO_URI)
stations = client.velib.stations

def fetch_weather(lat, lon):
    if not OW_KEY: return {}
    r = requests.get("https://api.openweathermap.org/data/2.5/weather",
                     params={"lat":lat,"lon":lon,"appid":OW_KEY,"units":"metric"})
    return r.json()

# Example: ingest stations CSV or simple generated data
def run_once():
    # For demo: insert 10 fake stations around Paris
    base = (48.8566, 2.3522)
    for i in range(1,21):
        lat = base[0] + (i%5)*0.001
        lon = base[1] + (i%5)*0.0015
        w = fetch_weather(lat, lon)
        doc = {
            "station_id": i,
            "name": f"Station {i}",
            "capacity": 20,
            "latitude": lat,
            "longitude": lon,
            "ts": datetime.utcnow().isoformat(),
            "available": max(0, 10 + (i%3) - (i%5))
        }
        stations.insert_one(doc)
    print("inserted demo stations")

if __name__=="__main__":
    run_once()

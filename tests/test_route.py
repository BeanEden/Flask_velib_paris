import requests
import json
from datetime import datetime, timedelta

URL = "http://localhost:5000/api/find_route"

def test_route_realtime():
    print("Testing Realtime Route...")
    # Coordonnées approximatives (Paris Centre)
    payload = {
        "start_lat": 48.8566,
        "start_lon": 2.3522,
        "end_lat": 48.8606,
        "end_lon": 2.3376,
        "time": datetime.now().isoformat()
    }
    try:
        res = requests.post(URL, json=payload)
        if res.status_code == 200:
            data = res.json()
            print("Success:", json.dumps(data, indent=2))
            if data['start_station'] and data['end_station']:
                print("✅ Found stations")
            else:
                print("⚠️ No stations found (might be empty DB or no availability)")
        else:
            print(f"❌ Error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")

def test_route_future():
    print("\nTesting Future Route...")
    future_time = (datetime.now() + timedelta(hours=5)).isoformat()
    payload = {
        "start_lat": 48.8566,
        "start_lon": 2.3522,
        "end_lat": 48.8606,
        "end_lon": 2.3376,
        "time": future_time
    }
    try:
        res = requests.post(URL, json=payload)
        if res.status_code == 200:
            data = res.json()
            print("Success:", json.dumps(data, indent=2))
        else:
            print(f"❌ Error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    test_route_realtime()
    test_route_future()

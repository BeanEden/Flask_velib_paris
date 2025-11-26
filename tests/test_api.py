import requests
import time

BASE = "http://localhost:5000"

def test_ingest_and_recommend():
    # ingest a station
    s = {"station_id":999, "capacity":12, "lat":48.8566, "lon":2.3522, "ts":"2025-11-17T12:00:00Z", "available":6}
    r = requests.post(BASE+"/ingest/station", json=s)
    assert r.status_code == 201

    # recommend: user near Paris center
    body = {"user":[48.8566,2.3522],"dest":[48.8584,2.2945],"radius_m":1000}
    r2 = requests.post(BASE+"/recommend", json=body)
    assert r2.status_code == 200
    d = r2.json()
    assert 'station' in d

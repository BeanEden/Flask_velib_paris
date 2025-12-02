import unittest
import requests
import json

class TestHourlyStats(unittest.TestCase):
    BASE_URL = "http://localhost:5000"

    def test_hourly_stats_structure(self):
        # Fetch some station IDs first
        response = requests.get(f"{self.BASE_URL}/api/map_data")
        self.assertEqual(response.status_code, 200)
        stations = response.json()
        if not stations:
            self.skipTest("No stations found to test")
        
        station_ids = [s['station_id'] for s in stations[:5]]
        
        # Test hourly stats endpoint
        payload = {'station_ids': station_ids}
        response = requests.post(f"{self.BASE_URL}/api/hourly_stats", json=payload)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertIn('data', data)
        self.assertIn('capacity', data)
        self.assertIsInstance(data['data'], list)
        self.assertEqual(len(data['data']), 24)
        self.assertIsInstance(data['capacity'], (int, float))
        
        # Check for nulls (should be present if no data for some hours)
        # This depends on data, but we expect at least some structure
        print(f"Capacity: {data['capacity']}")
        print(f"Data: {data['data']}")

if __name__ == '__main__':
    unittest.main()

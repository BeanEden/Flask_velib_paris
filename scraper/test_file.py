import os
from pymongo import MongoClient

uri = "mongodb+srv://bean3den:faRpFh6VyRLeEf6A@cluster0.wva85.mongodb.net/"
MONGODB_URL = "mongodb+srv://bean3den:faRpFh6VyRLeEf6A@cluster0.wva85.mongodb.net/"
print("URI =", "mongodb+srv://bean3den:qqXZHtsHqGZhMtQv@cluster0.wva85.mongodb.net/?appName=Cluster0")

client = MongoClient(uri)

print("Bases :", client.list_database_names())

db = client["Meteo"]
print("Collections :", db.list_collection_names())

collection = db["meteo"]
print("Document trouvé :", collection.find_one())

try:
    client.admin.command("ping")
    print("Connexion OK !")
except Exception as e:
    print("ERREUR :", e)

// Attendre que mongos soit prêt
print("Initialisation du sharding...");

// Ajouter les shards au cluster
sh.addShard("shard1/shard1a:27017")
sh.addShard("shard2/shard2a:27017")

// Activer le sharding sur la base et collections
sh.enableSharding("velib_data")
sh.shardCollection("velib_data.station", {"station_id": 1})
sh.shardCollection("velib_data.status", {"station_id": 1, "timestamp": 1})

print("Sharding configuré !");

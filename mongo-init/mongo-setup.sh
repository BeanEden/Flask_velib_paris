#!/bin/bash
set -e

echo "################################################"
echo "##     INITIALISATION DU CLUSTER MONGODB      ##"
echo "################################################"

# Fonction simple pour attendre qu'un serveur réponde
wait_for_host() {
    echo "⏳ En attente de $1:$2..."
    until mongosh --host $1 --port $2 --eval "print('alive')" > /dev/null 2>&1; do
        sleep 2
    done
    echo "✅ $1:$2 est en ligne."
}

# 1. On attend et on initie le Config Server
wait_for_host configsvr 27019
echo "⚙️  Configuration du Config Server..."
mongosh --host configsvr --port 27019 --eval 'rs.initiate({_id:"rsConfig", configsvr:true, members:[{_id:0, host:"configsvr:27019"}]})'

# 2. On attend et on initie le Shard 1
wait_for_host shard1 27018
echo "⚙️  Configuration du Shard 1..."
mongosh --host shard1 --port 27018 --eval 'rs.initiate({_id:"rsShard1", members:[{_id:0, host:"shard1:27018"}]})'

# 3. On attend et on initie le Shard 2
wait_for_host shard2 27020
echo "⚙️  Configuration du Shard 2..."
mongosh --host shard2 --port 27020 --eval 'rs.initiate({_id:"rsShard2", members:[{_id:0, host:"shard2:27020"}]})'

# 4. On configure le Routeur (Mongos)
# Le mongos a besoin que le configsvr soit prêt avant de démarrer.
# On attend que le mongos soit up (grâce au depends_on du docker-compose, il devrait arriver)
wait_for_host mongos 27017
echo "🔗 Liaison des shards au Routeur..."
mongosh --host mongos --port 27017 <<EOF
sh.addShard("rsShard1/shard1:27018")
sh.addShard("rsShard2/shard2:27020")
sh.enableSharding("velib")
sh.shardCollection("velib.stations", { station_id: "hashed" })
EOF

echo "################################################"
echo "##          INSTALLATION TERMINÉE             ##"
echo "################################################"
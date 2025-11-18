#!/bin/bash
set -e

echo "[setup] waiting for services..."
sleep 5

echo "[setup] initiate cfgRepl..."
mongosh --host configsvr:27019 <<EOF
rs.initiate({
  _id: "cfgRepl",
  configsvr: true,
  members: [{ _id: 0, host: "configsvr:27019" }]
})
EOF

sleep 5

echo "[setup] initiate shard1..."
mongosh --host shard1:27018 <<EOF
rs.initiate({
  _id: "shard1",
  members: [{ _id: 0, host: "shard1:27018" }]
})
EOF

echo "[setup] initiate shard2..."
mongosh --host shard2:27020 <<EOF
rs.initiate({
  _id: "shard2",
  members: [{ _id: 0, host: "shard2:27020" }]
})
EOF

sleep 5

echo "[setup] add shards to mongos..."
mongosh --host mongos:27017 <<EOF
sh.addShard("shard1/shard1:27018")
sh.addShard("shard2/shard2:27020")
EOF

echo "[setup] enable sharding on database velib"
mongosh --host mongos:27017 <<EOF
sh.enableSharding("velib")
sh.shardCollection("velib.stations", { station_id: "hashed" })
EOF

echo "[setup] DONE ✔️"

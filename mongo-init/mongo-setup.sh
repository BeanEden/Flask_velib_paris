#!/bin/sh
set -e
echo "[setup] waiting a bit for mongod services..."
sleep 6

# helper: use mongosh if present, else mongo
run_shell() {
  if command -v mongosh >/dev/null 2>&1; then
    mongosh -- "$@"
  else
    mongo -- "$@"
  fi
}

echo "[setup] initiate config replica set (rsConfig)..."
run_shell --host configsvr --port 27019 <<'EOF'
rs.initiate({_id:"rsConfig", configsvr:true, members:[{_id:0, host:"configsvr:27019"}]})
EOF

sleep 4

echo "[setup] initiate rsShard1..."
run_shell --host shard1 --port 27018 <<'EOF'
rs.initiate({_id:"rsShard1", members:[{_id:0, host:"shard1:27018"}]})
EOF

echo "[setup] initiate rsShard2..."
run_shell --host shard2 --port 27020 <<'EOF'
rs.initiate({_id:"rsShard2", members:[{_id:0, host:"shard2:27020"}]})
EOF

sleep 4

echo "[setup] add shards via mongos..."
run_shell --host mongos --port 27017 <<'EOF'
sh.addShard("rsShard1/shard1:27018")
sh.addShard("rsShard2/shard2:27020")
sh.status()
EOF

echo "[setup] enable sharding for velib and shard stations on station_id hashed..."
run_shell --host mongos --port 27017 <<'EOF'
sh.enableSharding("velib")
sh.shardCollection("velib.stations", { station_id: "hashed" })
sh.status()
EOF

echo "[setup] done."

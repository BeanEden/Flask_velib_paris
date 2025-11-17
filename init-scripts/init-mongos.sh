#!/bin/bash
sleep 15
mongosh tp1-mongos-1:27017 <<EOF
sh.addShard("shard1/tp1-shard1a-1:27017,tp1-shard1b-1:27017,tp1-shard1c-1:27017")
sh.addShard("shard2/tp1-shard2a-1:27017,tp1-shard2b-1:27017,tp1-shard2c-1:27017")
EOF

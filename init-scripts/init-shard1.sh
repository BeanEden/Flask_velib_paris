#!/bin/bash
sleep 5
mongosh tp1-shard1a-1:27017 <<EOF
rs.initiate({
  _id: "shard1",
  members: [
    { _id: 0, host: "tp1-shard1a-1:27017" },
    { _id: 1, host: "tp1-shard1b-1:27017" },
    { _id: 2, host: "tp1-shard1c-1:27017" }
  ]
})
EOF

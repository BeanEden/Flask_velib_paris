#!/bin/bash
sleep 5
mongosh tp1-shard2a-1:27017 <<EOF
rs.initiate({
  _id: "shard2",
  members: [
    { _id: 0, host: "tp1-shard2a-1:27017" },
    { _id: 1, host: "tp1-shard2b-1:27017" },
    { _id: 2, host: "tp1-shard2c-1:27017" }
  ]
})
EOF

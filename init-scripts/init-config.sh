#!/bin/bash
sleep 5
mongosh <<EOF
rs.initiate({
  _id: "configReplSet",
  configsvr: true,
  members: [
    { _id: 0, host: "tp1-configsvr1-1:27017" },
    { _id: 1, host: "tp1-configsvr2-1:27017" },
    { _id: 2, host: "tp1-configsvr3-1:27017" }
  ]
})
EOF

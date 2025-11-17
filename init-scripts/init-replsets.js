// Initialise les replica sets des shards et config server
rs.initiate({_id: "cfg", configsvr: true, members: [{_id: 0, host: "configsvr1:27017"}]})
rs.initiate({_id: "shard1", members: [{_id: 0, host: "shard1a:27017"}]})
rs.initiate({_id: "shard2", members: [{_id: 0, host: "shard2a:27017"}]})

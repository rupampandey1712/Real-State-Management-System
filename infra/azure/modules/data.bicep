// Data services (docs/azure-deployment.md §2): Postgres Flexible + pgvector (4 databases), Cosmos DB serverless,
// Service Bus Standard (topics/subscriptions mirroring infra/local/servicebus/Config.json with production
// TTL and duplicate windows), Storage (private media), Azure Cache for Redis (TLS only).
param prefix string
param location string
param tags object
@secure()
param postgresAdminPassword string
param postgresSku string = 'Standard_B2s'
param postgresTier string = 'Burstable'

var databases = [ 'identity', 'listing', 'search', 'ai' ]

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: 'pg-${prefix}'
  location: location
  tags: tags
  sku: { name: postgresSku, tier: postgresTier }
  properties: {
    version: '16'
    administratorLogin: 'estateadmin'
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 64, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 14, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' } // production: VNet integration / private endpoint (azure-deployment.md §6)
  }
}

resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'allow-azure-services'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource pgvector 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { value: 'VECTOR', source: 'user-override' }
}

resource dbs 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = [for db in databases: {
  parent: postgres
  name: db
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ pgvector ]
}]

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-${prefix}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0 } ]
    disableLocalAuth: false // services use the key until the managed-identity change (azure-deployment.md §3 #8)
    minimalTlsVersion: 'Tls12'
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'estateai'
  properties: { resource: { id: 'estateai' } } // containers are created by the services (store.py, telemetry_store.py)
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: 'sb-${prefix}'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard' }
  properties: { minimumTlsVersion: '1.2' }
}

// Keep in sync with infra/local/servicebus/Config.json and docs/architecture.md §4.
var topology = [
  { topic: 'listing-events', subscriptions: [ { name: 'search', lock: 'PT1M', deliveries: 5 }, { name: 'ai', lock: 'PT5M', deliveries: 3 } ] }
  { topic: 'ai-events', subscriptions: [ { name: 'listing', lock: 'PT1M', deliveries: 5 } ] }
  { topic: 'engagement-events', subscriptions: [ { name: 'notification', lock: 'PT1M', deliveries: 5 } ] }
  { topic: 'identity-events', subscriptions: [ { name: 'listing', lock: 'PT1M', deliveries: 5 }, { name: 'engagement', lock: 'PT1M', deliveries: 5 }, { name: 'ai', lock: 'PT1M', deliveries: 5 } ] }
]

resource topics 'Microsoft.ServiceBus/namespaces/topics@2024-01-01' = [for t in topology: {
  parent: serviceBus
  name: t.topic
  properties: {
    defaultMessageTimeToLive: 'P14D'
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
  }
}]

module subscriptions 'servicebus-subscriptions.bicep' = [for (t, i) in topology: {
  name: 'sb-subs-${t.topic}'
  params: { namespaceName: serviceBus.name, topicName: topics[i].name, subscriptions: t.subscriptions }
}]

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(replace('st${prefix}media', '-', ''), 24)
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: { deleteRetentionPolicy: { enabled: true, days: 14 } }
}

resource media 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'listing-media'
  properties: { publicAccess: 'None' }
}

resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: 'redis-${prefix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'Standard', family: 'C', capacity: 1 }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
}

output postgresHost string = postgres.properties.fullyQualifiedDomainName
output cosmosName string = cosmos.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output serviceBusName string = serviceBus.name
output storageName string = storage.name
output redisName string = redis.name
output redisHost string = redis.properties.hostName

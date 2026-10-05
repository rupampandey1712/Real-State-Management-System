// Container Registry, the apps' user-assigned identity, Key Vault (RBAC) with every secret the services read,
// and role assignments. One identity keeps the MVP simple; split per service for least privilege later.
param prefix string
param location string
param tags object
param postgresHost string
param cosmosName string
param serviceBusName string
param storageName string
param redisName string
@secure()
param postgresAdminPassword string
@secure()
param geminiApiKey string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: take(replace('${prefix}acr', '-', ''), 50)
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { adminUserEnabled: false }
}

resource appsIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-apps'
  location: location
  tags: tags
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('kv-${prefix}', 24)
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
  }
}

// Built-in role ids
var roles = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  blobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  serviceBusDataOwner: '090c5cfd-751d-490a-894a-3ce6f1109419'
}

resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, appsIdentity.id, roles.keyVaultSecretsUser)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: appsIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, appsIdentity.id, roles.acrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.acrPull)
    principalId: appsIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = { name: storageName }
resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' existing = { name: serviceBusName }
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = { name: cosmosName }
resource redis 'Microsoft.Cache/redis@2024-03-01' existing = { name: redisName }

// Ready for the managed-identity switch (azure-deployment.md §3 #8); connection strings below are used until then.
resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, appsIdentity.id, roles.blobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobDataContributor)
    principalId: appsIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource sbRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBus.id, appsIdentity.id, roles.serviceBusDataOwner)
  scope: serviceBus
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.serviceBusDataOwner)
    principalId: appsIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

var sbConnection = listKeys('${serviceBus.id}/AuthorizationRules/RootManageSharedAccessKey', serviceBus.apiVersion).primaryConnectionString
var storageKey = storage.listKeys().keys[0].value
var redisKey = redis.listKeys().primaryKey

var secrets = union({
  'servicebus-connection': sbConnection
  'storage-connection': 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storageKey};EndpointSuffix=${environment().suffixes.storage}'
  'cosmos-key': cosmos.listKeys().primaryMasterKey
  'redis-url': 'rediss://:${redisKey}@${redis.properties.hostName}:6380/0'
  'redis-gateway-connection': '${redis.properties.hostName}:6380,password=${redisKey},ssl=True,abortConnect=False'
  'gemini-api-key': empty(geminiApiKey) ? 'unset' : geminiApiKey
}, toObject([ 'identity', 'listing', 'search', 'ai' ], db => 'db-${db}', db => 'postgresql+asyncpg://estateadmin:${uriComponent(postgresAdminPassword)}@${postgresHost}:5432/${db}?ssl=require'))

var secretNames = [
  'servicebus-connection'
  'storage-connection'
  'cosmos-key'
  'redis-url'
  'redis-gateway-connection'
  'gemini-api-key'
  'db-identity'
  'db-listing'
  'db-search'
  'db-ai'
]

resource vaultSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [for name in secretNames: {
  parent: vault
  name: name
  properties: { value: secrets[name] }
}]

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output identityId string = appsIdentity.id
output identityClientId string = appsIdentity.properties.clientId
output vaultUri string = vault.properties.vaultUri

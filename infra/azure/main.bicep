// EstateAI on Azure (T4.12) — resource-group scope.
//   az group create -n rg-estateai-prod -l centralindia
//   az deployment group create -g rg-estateai-prod -f infra/azure/main.bicep -p infra/azure/main.prod.bicepparam
// Two phases on first install: deploy with `deployApps=false` (data, registry, vault, monitoring), push images
// (azure-deployment.md §4 step 2), then deploy again with `deployApps=true`. See docs/azure-deployment.md §4a.
targetScope = 'resourceGroup'

@minLength(3)
@maxLength(12)
param prefix string = 'estateai'
param location string = resourceGroup().location
@description('Container image tag pushed to ACR (CI uses the git SHA).')
param imageTag string = 'latest'
param deployApps bool = true
@description('Public URL users reach, e.g. https://www.estateai.in. Empty = the Front Door endpoint host.')
param publicBaseUrl string = ''
param alertEmail string
param googleClientId string = ''
@description('true runs the offline fake LLM (staging without a key). Production: false + geminiApiKey.')
param aiFake bool = false
@secure()
param postgresAdminPassword string
@secure()
param geminiApiKey string = ''

var tags = { app: 'estateai', env: prefix }

module data 'modules/data.bicep' = {
  name: 'data'
  params: { prefix: prefix, location: location, tags: tags, postgresAdminPassword: postgresAdminPassword }
}

module security 'modules/security.bicep' = {
  name: 'security'
  params: {
    prefix: prefix
    location: location
    tags: tags
    postgresHost: data.outputs.postgresHost
    cosmosName: data.outputs.cosmosName
    serviceBusName: data.outputs.serviceBusName
    storageName: data.outputs.storageName
    redisName: data.outputs.redisName
    postgresAdminPassword: postgresAdminPassword
    geminiApiKey: geminiApiKey
  }
}

// Workspace + App Insights here; availability tests and alerts (modules/monitoring.bicep) last, because
// they need the public URL, which needs Front Door, which needs the gateway.
resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${prefix}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}'
  location: location
  kind: 'web'
  tags: tags
  properties: { Application_Type: 'web', WorkspaceResourceId: workspace.id, DisableIpMasking: false } // NFR-5: no client IPs
}

module apps 'modules/apps.bicep' = if (deployApps) {
  name: 'apps'
  params: {
    prefix: prefix
    location: location
    tags: tags
    workspaceCustomerId: workspace.properties.customerId
    workspaceSharedKey: workspace.listKeys().primarySharedKey
    appInsightsConnectionString: appInsights.properties.ConnectionString
    acrLoginServer: security.outputs.acrLoginServer
    identityId: security.outputs.identityId
    vaultUri: security.outputs.vaultUri
    imageTag: imageTag
    cosmosEndpoint: data.outputs.cosmosEndpoint
    publicBaseUrl: publicBaseUrl
    googleClientId: googleClientId
    aiFake: aiFake
  }
}

module edge 'modules/edge.bicep' = if (deployApps) {
  name: 'edge'
  params: { prefix: prefix, tags: tags, gatewayFqdn: deployApps ? apps!.outputs.gatewayFqdn : '' }
}

var siteUrl = !empty(publicBaseUrl) ? publicBaseUrl : (deployApps ? 'https://${edge!.outputs.endpointHost}' : '')

module monitoring 'modules/monitoring.bicep' = if (deployApps) {
  name: 'monitoring'
  params: { prefix: prefix, location: location, tags: tags, appInsightsName: appInsights.name, alertEmail: alertEmail, publicBaseUrl: siteUrl }
}

output acrLoginServer string = security.outputs.acrLoginServer
output siteUrl string = siteUrl
output keyVaultUri string = security.outputs.vaultUri

// Container Apps environment, one app per service (docs/azure-deployment.md §4 step 7), migration jobs.
// Secrets are Key Vault references resolved with the apps' managed identity.
param prefix string
param location string
param tags object
param workspaceCustomerId string
@secure()
param workspaceSharedKey string
param appInsightsConnectionString string
param acrLoginServer string
param identityId string
param vaultUri string
param imageTag string
param cosmosEndpoint string
param publicBaseUrl string
param googleClientId string
param aiFake bool

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${prefix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: workspaceCustomerId, sharedKey: workspaceSharedKey }
    }
    // production: vnetConfiguration with an infrastructure subnet (azure-deployment.md §6)
  }
}

var kv = '${vaultUri}secrets'
func secretRef(name string, vault string, identity string) object => { name: name, keyVaultUrl: '${vault}/${name}', identity: identity }

var common = [
  { name: 'APP_ENV', value: 'prod' }
  { name: 'LOG_LEVEL', value: 'INFO' }
  { name: 'SERVICEBUS_CONNECTION', secretRef: 'servicebus-connection' }
  { name: 'REDIS_URL', secretRef: 'redis-url' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
  { name: 'IDENTITY_URL', value: 'http://identity' }
  { name: 'LISTING_URL', value: 'http://listing' }
  { name: 'SEARCH_URL', value: 'http://search' }
  { name: 'AI_URL', value: 'http://ai' }
  { name: 'ENGAGEMENT_URL', value: 'http://engagement' }
]
var commonSecrets = [ 'servicebus-connection', 'redis-url' ]

// name, extra env, extra secrets, min replicas (services with consumers/relays must stay ≥ 1), ingress
var services = [
  { name: 'identity', db: true, min: 1, env: [
    { name: 'WEB_BASE_URL', value: publicBaseUrl }
    { name: 'GOOGLE_CLIENT_ID', value: googleClientId }
  ], secrets: [] }
  { name: 'listing', db: true, min: 1, env: [
    { name: 'STORAGE_CONNECTION', secretRef: 'storage-connection' }
  ], secrets: [ 'storage-connection' ] }
  { name: 'search', db: true, min: 1, env: [], secrets: [] }
  { name: 'ai', db: true, min: 1, env: [
    { name: 'STORAGE_CONNECTION', secretRef: 'storage-connection' }
    { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
    { name: 'COSMOS_KEY', secretRef: 'cosmos-key' }
    { name: 'AI_FAKE', value: string(aiFake) }
    { name: 'EMBEDDING_PROVIDER', value: aiFake ? 'fake' : 'gemini' }
    { name: 'GEMINI_API_KEY', secretRef: 'gemini-api-key' }
  ], secrets: [ 'storage-connection', 'cosmos-key', 'gemini-api-key' ] }
  { name: 'engagement', db: false, min: 1, env: [
    { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
    { name: 'COSMOS_KEY', secretRef: 'cosmos-key' }
  ], secrets: [ 'cosmos-key' ] }
]

resource apps 'Microsoft.App/containerApps@2024-03-01' = [for svc in services: {
  name: svc.name
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: { external: false, targetPort: 8000, transport: 'http' }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: [for s in concat(commonSecrets, svc.secrets, svc.db ? [ 'db-${svc.name}' ] : []): secretRef(s, kv, identityId)]
    }
    template: {
      containers: [ {
        name: svc.name
        image: '${acrLoginServer}/${svc.name}:${imageTag}'
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: concat(common, [ { name: 'SERVICE_NAME', value: svc.name } ], svc.env,
          svc.db ? [ { name: 'DATABASE_URL', secretRef: 'db-${svc.name}' } ] : [])
        probes: [
          { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 10 }
          { type: 'Readiness', httpGet: { path: '/health/ready', port: 8000 }, periodSeconds: 10, failureThreshold: 3 }
        ]
      } ]
      scale: { minReplicas: svc.min, maxReplicas: 5, rules: [ { name: 'http', http: { metadata: { concurrentRequests: '50' } } } ] }
    }
  }
}]

resource notification 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'notification'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: [ secretRef('servicebus-connection', kv, identityId), secretRef('redis-url', kv, identityId) ]
    }
    template: {
      containers: [ {
        name: 'notification'
        image: '${acrLoginServer}/notification:${imageTag}'
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: concat(common, [
          { name: 'SERVICE_NAME', value: 'notification' }
          { name: 'WEB_BASE_URL', value: publicBaseUrl }
        ])
      } ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [ {
          name: 'sb-backlog'
          custom: {
            type: 'azure-servicebus'
            metadata: { topicName: 'engagement-events', subscriptionName: 'notification', messageCount: '20' }
            auth: [ { secretRef: 'servicebus-connection', triggerParameter: 'connection' } ]
          }
        } ]
      }
    }
  }
}

resource gateway 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'gateway'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: { external: true, targetPort: 8080, transport: 'http' }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: [ secretRef('redis-gateway-connection', kv, identityId) ]
    }
    template: {
      containers: [ {
        name: 'gateway'
        image: '${acrLoginServer}/gateway:${imageTag}'
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'ASPNETCORE_ENVIRONMENT', value: 'Production' }
          { name: 'Redis__ConnectionString', secretRef: 'redis-gateway-connection' }
          { name: 'Jwt__RequireHttpsMetadata', value: 'false' } // internal HTTP inside the environment
          { name: 'Jwt__MetadataAddress', value: 'http://identity/.well-known/openid-configuration' }
          { name: 'Cors__Origins__0', value: publicBaseUrl }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
          { name: 'ReverseProxy__Clusters__identity__Destinations__d1__Address', value: 'http://identity' }
          { name: 'ReverseProxy__Clusters__listing__Destinations__d1__Address', value: 'http://listing' }
          { name: 'ReverseProxy__Clusters__search__Destinations__d1__Address', value: 'http://search' }
          { name: 'ReverseProxy__Clusters__ai__Destinations__d1__Address', value: 'http://ai' }
          { name: 'ReverseProxy__Clusters__engagement__Destinations__d1__Address', value: 'http://engagement' }
        ]
        probes: [ { type: 'Readiness', httpGet: { path: '/health', port: 8080 }, periodSeconds: 10 } ]
      } ]
      scale: { minReplicas: 2, maxReplicas: 10 }
    }
  }
  dependsOn: [ apps ]
}

// Migrations run as manual jobs before each release (CI starts them): alembic upgrade head.
resource migrations 'Microsoft.App/jobs@2024-03-01' = [for db in [ 'identity', 'listing', 'search', 'ai' ]: {
  name: 'migrate-${db}'
  location: location
  tags: tags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [ { server: acrLoginServer, identity: identityId } ]
      secrets: [ secretRef('db-${db}', kv, identityId) ]
    }
    template: {
      containers: [ {
        name: 'migrate'
        image: '${acrLoginServer}/${db}:${imageTag}'
        command: [ 'alembic', 'upgrade', 'head' ]
        env: [ { name: 'DATABASE_URL', secretRef: 'db-${db}' }, { name: 'APP_ENV', value: 'prod' } ]
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      } ]
    }
  }
}]

output gatewayFqdn string = gateway.properties.configuration.ingress.fqdn

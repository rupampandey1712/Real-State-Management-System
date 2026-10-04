// One public domain (azure-deployment.md §1): Front Door routes /api/* to the gateway and everything else to
// Static Web Apps, so the SPA and API share a site and the SameSite=Strict refresh cookie works.
param prefix string
param tags object
param gatewayFqdn string
@description('Static Web Apps has a limited region list; Central India is not one of them.')
param staticWebAppLocation string = 'eastasia'

resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: 'swa-${prefix}'
  location: staticWebAppLocation
  tags: tags
  sku: { name: 'Standard', tier: 'Standard' }
  properties: {} // deployed by .github/workflows/deploy.yml (web/dist)
}

resource profile 'Microsoft.Cdn/profiles@2024-02-01' = {
  name: 'afd-${prefix}'
  location: 'global'
  tags: tags
  sku: { name: 'Standard_AzureFrontDoor' }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-02-01' = {
  parent: profile
  name: 'ep-${prefix}'
  location: 'global'
  properties: { enabledState: 'Enabled' }
}

resource webGroup 'Microsoft.Cdn/profiles/originGroups@2024-02-01' = {
  parent: profile
  name: 'web'
  properties: {
    loadBalancingSettings: { sampleSize: 4, successfulSamplesRequired: 3 }
    healthProbeSettings: { probePath: '/', probeProtocol: 'Https', probeRequestType: 'HEAD', probeIntervalInSeconds: 60 }
  }
}

resource apiGroup 'Microsoft.Cdn/profiles/originGroups@2024-02-01' = {
  parent: profile
  name: 'api'
  properties: {
    loadBalancingSettings: { sampleSize: 4, successfulSamplesRequired: 3 }
    healthProbeSettings: { probePath: '/health', probeProtocol: 'Https', probeRequestType: 'GET', probeIntervalInSeconds: 60 }
  }
}

resource webOrigin 'Microsoft.Cdn/profiles/originGroups/origins@2024-02-01' = {
  parent: webGroup
  name: 'web'
  properties: {
    hostName: swa.properties.defaultHostname
    originHostHeader: swa.properties.defaultHostname
    httpsPort: 443
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
  }
}

resource apiOrigin 'Microsoft.Cdn/profiles/originGroups/origins@2024-02-01' = {
  parent: apiGroup
  name: 'api'
  properties: {
    hostName: gatewayFqdn
    originHostHeader: gatewayFqdn
    httpsPort: 443
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
  }
}

resource apiRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-02-01' = {
  parent: endpoint
  name: 'api'
  properties: {
    originGroup: { id: apiGroup.id }
    patternsToMatch: [ '/api/*' ]
    supportedProtocols: [ 'Https' ]
    httpsRedirect: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    // no caching: the gateway's output cache decides; cookies and auth headers pass through
  }
  dependsOn: [ apiOrigin ]
}

resource webRoute 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-02-01' = {
  parent: endpoint
  name: 'web'
  properties: {
    originGroup: { id: webGroup.id }
    patternsToMatch: [ '/*' ]
    supportedProtocols: [ 'Http', 'Https' ]
    httpsRedirect: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    cacheConfiguration: { queryStringCachingBehavior: 'IgnoreQueryString', compressionSettings: { isCompressionEnabled: true, contentTypesToCompress: [ 'text/html', 'text/css', 'application/javascript', 'application/json', 'image/svg+xml' ] } }
  }
  dependsOn: [ webOrigin, apiRoute ]
}

output endpointHost string = endpoint.properties.hostName
output staticWebAppName string = swa.name

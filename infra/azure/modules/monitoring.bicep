// NFR-1 (99.5 % monthly) uptime signals on the existing Application Insights:
// availability tests from 5 regions against the site and /api/health/deep, and alerts to the on-call group.
param prefix string
param location string
param appInsightsName string
param alertEmail string
@description('Public base URL, e.g. https://www.estateai.in (Front Door endpoint until a custom domain exists).')
param publicBaseUrl string
param tags object

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource onCall 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: 'ag-${prefix}-oncall'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'estateoncall'
    enabled: true
    emailReceivers: [ { name: 'on-call', emailAddress: alertEmail, useCommonAlertSchema: true } ]
  }
}

// Five probe locations (Azure test-location ids): West Europe, East Asia, Southeast Asia, Central US, UK South.
var probeLocations = [ 'emea-nl-ams-azr', 'apac-hk-hkn-azr', 'apac-sg-sin-azr', 'us-il-ch1-azr', 'emea-gb-db3-azr' ]

var checks = [
  { name: 'web', url: publicBaseUrl, expected: 200 }
  { name: 'api', url: '${publicBaseUrl}/api/health/deep', expected: 200 }
]

resource availability 'Microsoft.Insights/webtests@2022-06-15' = [for check in checks: {
  name: 'avail-${prefix}-${check.name}'
  location: location
  tags: union(tags, { 'hidden-link:${appInsights.id}': 'Resource' })
  kind: 'standard'
  properties: {
    SyntheticMonitorId: 'avail-${prefix}-${check.name}'
    Name: '${check.name} is up'
    Enabled: true
    Frequency: 300
    Timeout: 30
    Kind: 'standard'
    RetryEnabled: true
    Locations: [for loc in probeLocations: { Id: loc }]
    Request: { RequestUrl: check.url, HttpVerb: 'GET', ParseDependentRequests: false }
    ValidationRules: { ExpectedHttpStatusCode: check.expected, SSLCheck: true, SSLCertRemainingLifetimeCheck: 14 }
  }
}]

// Down = 3 of 5 locations failing (one flaky region doesn't page anyone).
resource downAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = [for (check, i) in checks: {
  name: 'alert-${prefix}-${check.name}-down'
  location: 'global'
  tags: tags
  properties: {
    description: 'NFR-1: ${check.name} unreachable from 3+ regions. Runbook: docs/runbook.md#site-down'
    severity: 0
    enabled: true
    scopes: [ availability[i].id, appInsights.id ]
    evaluationFrequency: 'PT1M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.WebtestLocationAvailabilityCriteria'
      webTestId: availability[i].id
      componentId: appInsights.id
      failedLocationCount: 3
    }
    actions: [ { actionGroupId: onCall.id } ]
  }
}]

// Error budget: 99.5 %/month ≈ 3.6 h. Warn when daily availability of the API test drops below 99.5 %.
resource budgetAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${prefix}-availability-budget'
  location: 'global'
  tags: tags
  properties: {
    description: 'NFR-1 error budget: API availability under 99.5 % over 24 h. Runbook: docs/runbook.md#error-budget'
    severity: 2
    enabled: true
    scopes: [ appInsights.id ]
    evaluationFrequency: 'PT1H'
    windowSize: 'P1D'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [ {
        criterionType: 'StaticThresholdCriterion'
        name: 'availability'
        metricNamespace: 'microsoft.insights/components'
        metricName: 'availabilityResults/availabilityPercentage'
        dimensions: [ { name: 'availabilityResult/name', operator: 'Include', values: [ 'api is up' ] } ]
        operator: 'LessThan'
        threshold: json('99.5') // Bicep has no decimal literals
        timeAggregation: 'Average'
      } ]
    }
    actions: [ { actionGroupId: onCall.id } ]
  }
}

// NFR-8: API latency — p95-ish signal from server request duration, and 5xx rate.
resource errorRateAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${prefix}-5xx'
  location: 'global'
  tags: tags
  properties: {
    description: 'More than 2 % of requests failing over 15 minutes. Runbook: docs/runbook.md#errors'
    severity: 1
    enabled: true
    scopes: [ appInsights.id ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [ {
        criterionType: 'StaticThresholdCriterion'
        name: 'failed'
        metricNamespace: 'microsoft.insights/components'
        metricName: 'requests/failed'
        operator: 'GreaterThan'
        threshold: 20
        timeAggregation: 'Count'
      } ]
    }
    actions: [ { actionGroupId: onCall.id } ]
  }
}

resource latencyAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'alert-${prefix}-latency'
  location: 'global'
  tags: tags
  properties: {
    description: 'NFR-8: average server response time over 300 ms for 15 minutes. Runbook: docs/runbook.md#slow'
    severity: 2
    enabled: true
    scopes: [ appInsights.id ]
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [ {
        criterionType: 'StaticThresholdCriterion'
        name: 'duration'
        metricNamespace: 'microsoft.insights/components'
        metricName: 'requests/duration'
        operator: 'GreaterThan'
        threshold: 300
        timeAggregation: 'Average'
      } ]
    }
    actions: [ { actionGroupId: onCall.id } ]
  }
}

output actionGroupId string = onCall.id

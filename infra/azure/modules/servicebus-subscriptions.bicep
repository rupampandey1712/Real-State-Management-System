// Subscriptions of one topic (a nested loop is not allowed inside data.bicep's topic loop).
param namespaceName string
param topicName string
param subscriptions array

resource subs 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2024-01-01' = [for s in subscriptions: {
  name: '${namespaceName}/${topicName}/${s.name}'
  properties: {
    lockDuration: s.lock
    maxDeliveryCount: s.deliveries
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P14D'
  }
}]

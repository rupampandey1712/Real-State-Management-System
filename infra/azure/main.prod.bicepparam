// Production parameters. Secrets come from the environment (CI: GitHub environment secrets), never this file.
using 'main.bicep'

param prefix = 'estateai'
param location = 'centralindia'
param imageTag = readEnvironmentVariable('IMAGE_TAG', 'latest')
param deployApps = bool(readEnvironmentVariable('DEPLOY_APPS', 'true'))
param publicBaseUrl = readEnvironmentVariable('PUBLIC_BASE_URL', '')
param alertEmail = readEnvironmentVariable('ALERT_EMAIL', 'oncall@example.com')
param googleClientId = readEnvironmentVariable('GOOGLE_CLIENT_ID', '')
param aiFake = false
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param geminiApiKey = readEnvironmentVariable('GEMINI_API_KEY', '')

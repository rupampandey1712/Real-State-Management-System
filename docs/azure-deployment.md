# Deploying EstateAI to Azure

> What to create in Azure, what to change in code and configuration first, how to deploy step by step, and how
> to run it afterwards. Local development stays on emulators ([getting-started.md](getting-started.md)); this
> document maps each piece to its Azure service (see also [architecture.md §7](architecture.md) and
> [integrations.md](integrations.md)).
>
> **Status:** the system has been run end to end locally, not yet in Azure. The commands below are a manual
> walkthrough; the target is Bicep + `azd` in CI (task T4.12). Region used in examples: **Central India** (`centralindia`).

---

## 1. Target architecture

```
                      ┌──────────────── Azure Front Door (one domain: www.estateai.in) ────────────────┐
  Users ── HTTPS ───▶ │  /*      → Static Web Apps (React SPA)                                          │
                      │  /api/*  → Container Apps: gateway (YARP, external ingress)                      │
                      └───────────────────────────────────┬────────────────────────────────────────────┘
                                                          │  (private: Container Apps environment in a VNet)
     ┌──────────┬──────────┬──────────┬──────────┬────────┴───┬──────────────┬──────────────────────────┐
     identity   listing    search     ai         engagement   notification   jobs: migrate-*, outbox-cleanup
     (internal ingress, min 1 replica each; notification scales on Service Bus with KEDA)
        │          │          │         │            │              │
   PostgreSQL Flexible (identity, listing, search, ai DBs; pgvector)   Cosmos DB (serverless)
   Azure Cache for Redis / Azure Managed Redis                          Service Bus Standard (3 topics)
   Storage account (listing-media, private)                            Key Vault (secrets, signing keys)
   Communication Services Email                                        Application Insights + Log Analytics
   Container Registry                                                  Outbound HTTPS → Gemini API
```

**Why Front Door with one domain:** the refresh token is an httpOnly cookie with `SameSite=Strict`, scoped to
`/api/v1/auth`. The browser only sends it if the SPA and the API are on the **same site**. Serving the SPA and `/api/*`
from one Front Door domain keeps cookies first-party and removes CORS entirely.

## 2. Resource list

| Local | Azure resource | Suggested starting SKU | Notes |
|---|---|---|---|
| docker compose | **Container Apps environment** (workload profiles, VNet-integrated) | Consumption | One app per service, plus jobs |
| image builds | **Azure Container Registry** | Basic → Standard | Pull via managed identity (`AcrPull`) |
| nginx `web` | **Static Web Apps** | Standard | Or Storage static website behind Front Door |
| — | **Azure Front Door** | Standard | TLS, WAF (Premium for managed rules), routing |
| Postgres + pgvector | **PostgreSQL Flexible Server** 16 | Burstable B2s (dev) / General Purpose D2ds_v5 (prod) | Allow-list `VECTOR`; 4 databases |
| Redis | **Azure Managed Redis** or **Azure Cache for Redis** | Balanced B0 / Standard C1 | TLS only |
| Cosmos emulator | **Cosmos DB for NoSQL** | Serverless | Database `estateai` |
| Service Bus emulator + SQL Server | **Service Bus** namespace | **Standard** (topics need Standard+) | Duplicate detection, TTL |
| Azurite | **Storage account** (StorageV2) | Standard LRS/ZRS | Private container `listing-media` |
| Mailpit | **Communication Services** + Email Communication Service | pay-as-you-go | Verified sender domain |
| Aspire Dashboard | **Application Insights** + Log Analytics workspace | pay-as-you-go | OpenTelemetry |
| `.env` | **Key Vault** | Standard, RBAC | All secrets; JWT signing keys (T4.14) |
| — | **User-assigned managed identity** per service | — | Key Vault, ACR, Storage, Service Bus, Cosmos access |

## 3. Code and configuration changes before production

These are required or strongly recommended; each is small. Items marked **required** will break or be insecure otherwise.

| # | Change | Why | Where |
|---|---|---|---|
| 1 | **Required:** `APP_ENV=prod` for every service | Disables `/docs`, dev seed/republish endpoints, `dev_code` in sign-in responses, dev users; makes the refresh cookie `Secure` | env |
| 2 | **Required:** JWT signing keys out of Postgres into Key Vault (T4.14) | Private keys must not live in the app database | `services/identity/app/tokens.py` (load/sign via Key Vault or load PEM from a Key Vault secret at start) |
| 3 | **Required:** Service Bus topic settings for production: TTL e.g. `P14D`, duplicate window `PT10M` | The local values (1 h / 5 min) are emulator limits | IaC (below), not `Config.json` |
| 4 | **Required:** Redis over TLS | Azure Redis only accepts TLS | `REDIS_URL=rediss://…:6380/0` (Cache for Redis) or `:10000` (Managed Redis); gateway `Redis__ConnectionString=<host>:6380,password=…,ssl=True,abortConnect=False` |
| 5 | **Required:** email via Azure Communication Services | Mailpit is local only | Either ACS SMTP (`SMTP_HOST=smtp.azurecomm.net`, port 587, STARTTLS + Entra app credentials — add username/password/TLS settings to `otp.py` and `notification/main.py`) or switch to the ACS Email SDK |
| 6 | **Required:** gateway JWT metadata over the internal network | `Jwt:RequireHttpsMetadata` is `true` by default | Either use the identity app's internal HTTPS FQDN (`https://identity.internal.<env-domain>/.well-known/openid-configuration`) or set `Jwt__RequireHttpsMetadata=false` for the internal HTTP URL (traffic stays inside the environment) |
| 7 | **Required:** gateway cluster addresses and CORS | Service DNS names differ | `ReverseProxy__Clusters__<svc>__Destinations__d1__Address=http://<svc>` (internal ingress, port 80 → target 8000); `Cors__Origins__0=https://www.estateai.in` (unused with one domain but harmless) |
| 8 | Recommended: managed identity instead of connection strings for Service Bus, Storage, Cosmos | No secrets to rotate | Replace `from_connection_string(...)` with `ServiceBusClient(fully_qualified_namespace, DefaultAzureCredential())`, `BlobServiceClient(account_url, credential)`, `CosmosClient(url, credential)`; add `azure-identity`. Until then, keep the connection strings in Key Vault |
| 9 | Recommended: Postgres with Entra ID auth | No DB password | asyncpg with an access token as password (refresh before expiry), or a Key Vault secret for now |
| 10 | Recommended: serve images from Blob via Front Door/CDN | Offload `/api/v1/media/*` from the listing service | Front Door origin → storage (private link) or short-lived SAS URLs in `mapping.py` |
| 11 | Recommended: self-host the Mukta font | Removes the only third-party browser call | `web/index.html` → local font files |
| 12 | Recommended: outbox cleanup job (T4.15) | `outbox` grows forever | Container Apps scheduled job: `DELETE FROM outbox WHERE published_at < now() - interval '7 days'` |
| 13 | Gemini: paid-tier key in Key Vault, outbound HTTPS allowed | Free tier data terms; NSG/firewall egress | `GEMINI_API_KEY` secret; egress to `generativelanguage.googleapis.com` |

## 4a. Infrastructure as code (Bicep) — the recommended path

Everything in §2 and §4 is declared in `infra/azure/` (T4.12). `main.bicep` wires the modules:

| Module | Creates |
|---|---|
| `modules/data.bicep` | PostgreSQL Flexible 16 (pgvector allow-listed, 4 databases, 14-day backups) · Cosmos DB serverless + `estateai` database · Service Bus Standard with all four topics and their subscriptions (mirrors `Config.json`, production TTL `P14D`, duplicate window `PT10M`) · Storage (ZRS, private `listing-media`, soft delete) · Azure Cache for Redis (TLS only) |
| `modules/security.bicep` | Container Registry · one user-assigned identity for the apps · Key Vault (RBAC, purge protection) with every secret the services read · role assignments (Key Vault Secrets User, AcrPull, Blob Data Contributor, Service Bus Data Owner) |
| `modules/apps.bicep` | Container Apps environment · identity, listing, search, ai, engagement (internal ingress, ≥ 1 replica, liveness/readiness probes) · gateway (external, ≥ 2 replicas) · notification (KEDA Service Bus scaler, 0–3) · `migrate-*` jobs |
| `modules/edge.bicep` | Static Web App · Front Door Standard with `/api/*` → gateway and `/*` → SPA on one domain |
| `modules/monitoring.bicep` | NFR-1 uptime: availability tests for the site and `/api/health/deep` from 5 regions every 5 min; alerts (site/API down, 24 h availability < 99.5 %, 5xx count, response time > 300 ms) to an on-call email group. Playbooks: [runbook.md](runbook.md) §6–6c |

```bash
az group create -n rg-estateai-prod -l centralindia
export POSTGRES_ADMIN_PASSWORD='<from a password manager>' GEMINI_API_KEY='<paid-tier key>' ALERT_EMAIL=oncall@estateai.in

# 1st run: data, registry, vault, workspace — no apps yet (their images don't exist)
DEPLOY_APPS=false az deployment group create -g rg-estateai-prod -f infra/azure/main.bicep -p infra/azure/main.prod.bicepparam
# push images (§4 step 2) with a tag, then deploy everything
IMAGE_TAG=1.0.0 az deployment group create -g rg-estateai-prod -f infra/azure/main.bicep -p infra/azure/main.prod.bicepparam
for s in identity listing search ai; do az containerapp job start -g rg-estateai-prod -n migrate-$s; done

az bicep build --file infra/azure/main.bicep          # compile check (CI runs this)
az deployment group what-if -g rg-estateai-prod -f infra/azure/main.bicep -p infra/azure/main.prod.bicepparam
```

Still manual or deliberately left out of the templates: the custom domain + certificate on Front Door, the ACS
Email domain (§3 #5), VNet integration and private endpoints (§6 — the templates use public endpoints with
Azure-services-only firewall rules so a first environment can come up quickly), Key Vault signing keys (T4.14),
and the managed-identity switch for Storage/Service Bus/Cosmos (§3 #8 — the role assignments already exist).
Telemetry: services export OTLP; enable the Container Apps managed OpenTelemetry agent with App Insights as the
destination (environment → Monitoring → OpenTelemetry) until it is added to `apps.bicep`.

## 4. Step-by-step (Azure CLI)

Prerequisites: Azure CLI ≥ 2.60 with `containerapp` extension (`az extension add -n containerapp`), Owner or
Contributor + User Access Administrator on the subscription, a domain name for Front Door.

```bash
# ── 0. Variables ─────────────────────────────────────────────────────────────
RG=rg-estateai-prod; LOC=centralindia; PREFIX=estateai
ACR=${PREFIX}acr; ENV=cae-${PREFIX}; KV=kv-${PREFIX}; PG=pg-${PREFIX}; SB=sb-${PREFIX}
COSMOS=cosmos-${PREFIX}; ST=st${PREFIX}media; REDIS=redis-${PREFIX}; LAW=law-${PREFIX}; AI=appi-${PREFIX}
az group create -n $RG -l $LOC

# ── 1. Monitoring ────────────────────────────────────────────────────────────
az monitor log-analytics workspace create -g $RG -n $LAW -l $LOC
LAW_ID=$(az monitor log-analytics workspace show -g $RG -n $LAW --query customerId -o tsv)
LAW_KEY=$(az monitor log-analytics workspace get-shared-keys -g $RG -n $LAW --query primarySharedKey -o tsv)
az monitor app-insights component create -g $RG -a $AI -l $LOC --workspace $LAW   # needs the application-insights extension

# ── 2. Registry and images ───────────────────────────────────────────────────
az acr create -g $RG -n $ACR --sku Standard
for svc in identity listing search ai engagement notification; do
  az acr build -r $ACR -t $svc:1.0.0 -f services/$svc/Dockerfile .          # build context = repo root
done
az acr build -r $ACR -t gateway:1.0.0 services/gateway                        # build context = services/gateway

# ── 3. Identity and secrets ──────────────────────────────────────────────────
az identity create -g $RG -n id-${PREFIX}-apps
MI_ID=$(az identity show -g $RG -n id-${PREFIX}-apps --query id -o tsv)
MI_PRINCIPAL=$(az identity show -g $RG -n id-${PREFIX}-apps --query principalId -o tsv)
az keyvault create -g $RG -n $KV -l $LOC --enable-rbac-authorization true
az role assignment create --assignee $MI_PRINCIPAL --role "Key Vault Secrets User" \
  --scope $(az keyvault show -n $KV --query id -o tsv)
az role assignment create --assignee $MI_PRINCIPAL --role AcrPull --scope $(az acr show -n $ACR --query id -o tsv)
# (one identity keeps the walkthrough short; use one per service in production for least privilege)

# ── 4. Data services ─────────────────────────────────────────────────────────
az postgres flexible-server create -g $RG -n $PG -l $LOC --version 16 --tier Burstable --sku-name Standard_B2s \
  --storage-size 64 --admin-user estateadmin --admin-password "<from a password manager>" --public-access None
az postgres flexible-server parameter set -g $RG -s $PG --name azure.extensions --value VECTOR
for db in identity listing search ai; do az postgres flexible-server db create -g $RG -s $PG -d $db; done
# (with --public-access None, add VNet integration or a private endpoint so the Container Apps environment can reach it)

az cosmosdb create -g $RG -n $COSMOS --capabilities EnableServerless --default-consistency-level Session
az cosmosdb sql database create -g $RG -a $COSMOS -n estateai           # containers are created by the services

az servicebus namespace create -g $RG -n $SB -l $LOC --sku Standard
for topic in listing-events ai-events engagement-events identity-events; do
  az servicebus topic create -g $RG --namespace-name $SB -n $topic \
    --default-message-time-to-live P14D --enable-duplicate-detection true --duplicate-detection-history-time-window PT10M
done
az servicebus topic subscription create -g $RG --namespace-name $SB --topic-name listing-events -n search --max-delivery-count 5 --lock-duration PT1M --dead-letter-on-message-expiration true
az servicebus topic subscription create -g $RG --namespace-name $SB --topic-name listing-events -n ai --max-delivery-count 3 --lock-duration PT5M --dead-letter-on-message-expiration true
az servicebus topic subscription create -g $RG --namespace-name $SB --topic-name ai-events -n listing --max-delivery-count 5 --lock-duration PT1M --dead-letter-on-message-expiration true
az servicebus topic subscription create -g $RG --namespace-name $SB --topic-name engagement-events -n notification --max-delivery-count 5 --lock-duration PT1M --dead-letter-on-message-expiration true
for sub in listing engagement ai; do
  az servicebus topic subscription create -g $RG --namespace-name $SB --topic-name identity-events -n $sub --max-delivery-count 5 --lock-duration PT1M --dead-letter-on-message-expiration true
done

az storage account create -g $RG -n $ST -l $LOC --sku Standard_ZRS --kind StorageV2 --allow-blob-public-access false --min-tls-version TLS1_2
az storage container create --account-name $ST -n listing-media --auth-mode login

az redis create -g $RG -n $REDIS -l $LOC --sku Standard --vm-size c1 --minimum-tls-version 1.2
# (or Azure Managed Redis: az redisenterprise create …)

# ── 5. Secrets into Key Vault (connection strings until the managed-identity change in §3 #8) ──
az keyvault secret set --vault-name $KV -n servicebus-connection --value "$(az servicebus namespace authorization-rule keys list -g $RG --namespace-name $SB -n RootManageSharedAccessKey --query primaryConnectionString -o tsv)"
az keyvault secret set --vault-name $KV -n storage-connection   --value "$(az storage account show-connection-string -g $RG -n $ST -o tsv)"
az keyvault secret set --vault-name $KV -n cosmos-key            --value "$(az cosmosdb keys list -g $RG -n $COSMOS --query primaryMasterKey -o tsv)"
az keyvault secret set --vault-name $KV -n redis-url             --value "rediss://:$(az redis list-keys -g $RG -n $REDIS --query primaryKey -o tsv)@$REDIS.redis.cache.windows.net:6380/0"
az keyvault secret set --vault-name $KV -n redis-gateway-connection --value "$REDIS.redis.cache.windows.net:6380,password=$(az redis list-keys -g $RG -n $REDIS --query primaryKey -o tsv),ssl=True,abortConnect=False"   # StackExchange.Redis format
az keyvault secret set --vault-name $KV -n gemini-api-key        --value "<paid-tier key>"
for db in identity listing search ai; do
  az keyvault secret set --vault-name $KV -n db-$db --value "postgresql+asyncpg://estateadmin:<password>@$PG.postgres.database.azure.com:5432/$db?ssl=require"
done

# ── 6. Container Apps environment ────────────────────────────────────────────
az containerapp env create -g $RG -n $ENV -l $LOC --logs-workspace-id $LAW_ID --logs-workspace-key $LAW_KEY
# production: add --infrastructure-subnet-resource-id <subnet> (VNet) and --internal-only false

# ── 7. One app per service (example: listing; repeat with each service's env vars) ──
KVURI=https://$KV.vault.azure.net/secrets
az containerapp create -g $RG -n listing --environment $ENV --image $ACR.azurecr.io/listing:1.0.0 \
  --registry-server $ACR.azurecr.io --registry-identity $MI_ID --user-assigned $MI_ID \
  --ingress internal --target-port 8000 --min-replicas 1 --max-replicas 5 --cpu 0.5 --memory 1Gi \
  --secrets "db=keyvaultref:$KVURI/db-listing,identityref:$MI_ID" \
            "sb=keyvaultref:$KVURI/servicebus-connection,identityref:$MI_ID" \
            "st=keyvaultref:$KVURI/storage-connection,identityref:$MI_ID" \
            "redis=keyvaultref:$KVURI/redis-url,identityref:$MI_ID" \
  --env-vars APP_ENV=prod SERVICE_NAME=listing DATABASE_URL=secretref:db SERVICEBUS_CONNECTION=secretref:sb \
             STORAGE_CONNECTION=secretref:st REDIS_URL=secretref:redis IDENTITY_URL=http://identity \
             AI_URL=http://ai OTEL_EXPORTER_OTLP_ENDPOINT=<OTLP endpoint of the environment's OpenTelemetry agent>
# health probes: liveness GET /health, readiness GET /health/ready (az containerapp update … --yaml with probes)

# gateway: external ingress on 8080
az containerapp create -g $RG -n gateway --environment $ENV --image $ACR.azurecr.io/gateway:1.0.0 \
  --registry-server $ACR.azurecr.io --registry-identity $MI_ID --user-assigned $MI_ID \
  --ingress external --target-port 8080 --min-replicas 2 --max-replicas 10 \
  --secrets "redis-gw=keyvaultref:$KVURI/redis-gateway-connection,identityref:$MI_ID" \
  --env-vars ASPNETCORE_ENVIRONMENT=Production Redis__ConnectionString=secretref:redis-gw Jwt__RequireHttpsMetadata=false \
             Jwt__MetadataAddress=http://identity/.well-known/openid-configuration \
             ReverseProxy__Clusters__identity__Destinations__d1__Address=http://identity \
             ReverseProxy__Clusters__listing__Destinations__d1__Address=http://listing \
             ReverseProxy__Clusters__search__Destinations__d1__Address=http://search \
             ReverseProxy__Clusters__ai__Destinations__d1__Address=http://ai \
             ReverseProxy__Clusters__engagement__Destinations__d1__Address=http://engagement

# notification: no ingress; scale on the subscription backlog (KEDA)
az containerapp create -g $RG -n notification --environment $ENV --image $ACR.azurecr.io/notification:1.0.0 \
  --registry-server $ACR.azurecr.io --registry-identity $MI_ID --user-assigned $MI_ID --min-replicas 0 --max-replicas 3 \
  --secrets "sb=keyvaultref:$KVURI/servicebus-connection,identityref:$MI_ID" \
  --env-vars APP_ENV=prod SERVICEBUS_CONNECTION=secretref:sb IDENTITY_URL=http://identity ENGAGEMENT_URL=http://engagement \
  --scale-rule-name sb-backlog --scale-rule-type azure-servicebus \
  --scale-rule-metadata topicName=engagement-events subscriptionName=notification messageCount=20 \
  --scale-rule-auth connection=sb

# ── 8. Migrations as jobs (run before each release) ──────────────────────────
for svc in identity listing search ai; do
  az containerapp job create -g $RG -n migrate-$svc --environment $ENV --trigger-type Manual --replica-timeout 600 \
    --image $ACR.azurecr.io/$svc:1.0.0 --registry-server $ACR.azurecr.io --registry-identity $MI_ID --user-assigned $MI_ID \
    --secrets "db=keyvaultref:$KVURI/db-$svc,identityref:$MI_ID" --env-vars DATABASE_URL=secretref:db \
    --command "alembic" --args "upgrade" "head"
  az containerapp job start -g $RG -n migrate-$svc
done

# ── 9. Frontend and Front Door ───────────────────────────────────────────────
az staticwebapp create -g $RG -n swa-$PREFIX -l eastasia --sku Standard      # SWA has a limited region list
# deploy web/dist with the SWA GitHub Action or `swa deploy` (build: cd web && npm ci && npm run build)
az afd profile create -g $RG --profile-name afd-$PREFIX --sku Standard_AzureFrontDoor
# endpoint + custom domain + two origin groups: "web" (SWA hostname) and "api" (gateway FQDN);
# routes: /api/*  → api (caching disabled, forward all headers/cookies);  /*  → web (caching enabled)
```

**Service-by-service settings** (beyond `APP_ENV`, `SERVICE_NAME`, `REDIS_URL`, `SERVICEBUS_CONNECTION`, `OTEL_*`):

| Service | Min replicas | Extra settings |
|---|---|---|
| gateway | 2 | as above; `RateLimits__*` overrides if needed |
| identity | 1 | `DATABASE_URL`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_TTL_S`, `SMTP_*`, `EMAIL_FROM`, `IDENTITY_URL=http://identity` (JWKS URL advertised to verifiers) |
| listing | 1 (runs the outbox relay and a consumer) | `DATABASE_URL`, `STORAGE_CONNECTION`, `MEDIA_CONTAINER`, `IDENTITY_URL`, `AI_URL` |
| search | 1 (consumer) | `DATABASE_URL`, `AI_URL`, `EMBEDDING_DIM` |
| ai | 1 (consumer + relay) | `DATABASE_URL`, `STORAGE_CONNECTION`, `COSMOS_*`, `LISTING_URL`, `AI_FAKE=false`, `GEMINI_API_KEY`, `EMBEDDING_PROVIDER=gemini`, `AI_MODEL_*` |
| engagement | 1 (relay) | `COSMOS_*`, `LISTING_URL` |
| notification | 0 (KEDA) | `SMTP_*`, `EMAIL_FROM`, `WEB_BASE_URL=https://www.estateai.in`, `IDENTITY_URL`, `ENGAGEMENT_URL` |

Services with background consumers or relays must keep **at least one replica** — scale-to-zero would stop event processing.

## 5. CI/CD (GitHub Actions)

Use OpenID Connect federation (no stored Azure secrets): an Entra app/managed identity with a federated credential for
the repository, and `azure/login@v2` with `client-id`, `tenant-id`, `subscription-id`.

```yaml
# .github/workflows/deploy.yml (outline)
on: { push: { branches: [main] } }
permissions: { id-token: write, contents: read }
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r libs/common/requirements.txt -r libs/common/requirements-dev.txt
      - run: cd libs/common && pytest -q                       # + each service's tests
      - run: cd services/gateway && dotnet test
      - run: cd web && npm ci && npm run build
      - run: python scripts/check_api_sync.py
  deploy:
    needs: test
    runs-on: ubuntu-latest
    environment: production                                   # manual approval gate
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with: { client-id: ${{ vars.AZURE_CLIENT_ID }}, tenant-id: ${{ vars.AZURE_TENANT_ID }}, subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }} }
      - run: |                                                 # build all images with the commit SHA as tag
          for s in identity listing search ai engagement notification; do az acr build -r $ACR -t $s:${{ github.sha }} -f services/$s/Dockerfile .; done
          az acr build -r $ACR -t gateway:${{ github.sha }} services/gateway
      - run: |                                                 # migrations first, then roll out
          for s in identity listing search ai; do
            az containerapp job update -g $RG -n migrate-$s --image $ACR.azurecr.io/$s:${{ github.sha }}
            az containerapp job start -g $RG -n migrate-$s   # wait for success before continuing
          done
          for s in identity listing search ai engagement notification gateway; do
            az containerapp update -g $RG -n $s --image $ACR.azurecr.io/$s:${{ github.sha }}
          done
      # web: Azure/static-web-apps-deploy@v1 with app_location: web, output_location: dist
```

Container Apps revisions give instant rollback (`az containerapp revision activate`). Migrations must be backward
compatible with the previous release (expand → deploy → contract), because old and new revisions run side by side.

## 6. Security checklist for Azure

- [ ] All secrets in Key Vault; apps read them through Key Vault references with managed identity; no secrets in env files or images.
- [ ] Postgres, Cosmos, Service Bus, Storage, Redis, Key Vault: **private endpoints** or VNet rules; public network access disabled.
- [ ] Only the gateway has external ingress, and only Front Door can reach it (restrict to Front Door's service tag + `X-Azure-FDID` header check).
- [ ] Front Door WAF (Premium) with OWASP managed rules and a rate-limit rule as an outer layer.
- [ ] `APP_ENV=prod` everywhere; `/docs` off; dev endpoints return 404.
- [ ] JWT signing keys in Key Vault (T4.14); rotation schedule set; JWKS reachable internally only.
- [ ] Defender for Cloud on the subscription; image scanning in ACR.
- [ ] Diagnostic settings → Log Analytics for every resource; alerts from [runbook.md](runbook.md) (LLM error rate, dead-letter count, outbox backlog, 5xx rate, p95 latency).
- [ ] Backups: Postgres PITR (7–35 days), Cosmos continuous backup, Storage soft delete + versioning.

## 7. Operating in Azure

| Task | How |
|---|---|
| Logs for one request | Log Analytics: `ContainerAppConsoleLogs_CL \| where Log_s contains "<request id>"` |
| Distributed trace | Application Insights → Transaction search → request id / operation id |
| Dead letters | Service Bus Explorer (portal) → topic → subscription → Dead-letter |
| Outbox backlog | `select count(*) from outbox where published_at is null;` (listing and ai DBs) |
| Scale | `az containerapp update -n <app> --min-replicas … --max-replicas …` |
| Roll back | `az containerapp revision list -n <app>` → `az containerapp revision activate --revision <old>` |
| Rotate JWT keys | `POST /api/v1/admin/keys/rotate` (admin) |
| Rotate infrastructure keys | Regenerate in the resource → update the Key Vault secret → restart revisions (or switch to managed identity, §3 #8) |

## 8. Rough monthly cost (small production, Central India, pay-as-you-go)

| Item | Estimate (USD) |
|---|---|
| Container Apps (7 apps, ~0.5 vCPU / 1 GiB each, always on) | 150–250 |
| PostgreSQL Flexible Server General Purpose D2ds_v5 + 128 GB | 150–200 |
| Azure Cache for Redis Standard C1 | 100 |
| Service Bus Standard | 10 + operations |
| Cosmos DB serverless | 10–50 (usage-based) |
| Storage, Front Door Standard, Static Web Apps Standard, Key Vault | 50–80 |
| Application Insights / Log Analytics | 30–100 (ingestion-based) |
| **Azure total** | **≈ 500–800** |
| Gemini API | usage-based (see `services/ai/app/pricing.py`; 3.8 Flash pricing doubles after 2026-12-31) |

Check current prices with the Azure Pricing Calculator; these are planning figures, not quotes.

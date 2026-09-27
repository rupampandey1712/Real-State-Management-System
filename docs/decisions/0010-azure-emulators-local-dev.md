# 0010 — Azure emulators for local development
- Status: Accepted
- Date: 2026-09-27
- Deciders: Tech lead
- Related: docs/architecture.md §6, docker-compose.yml

## Context
Developers and AI coding agents must be able to run the entire system offline, with no Azure
subscription, and with the same SDKs and connection-string shapes used in production.

## Decision
One `docker compose up` runs every dependency, using official Microsoft emulators where they exist
and protocol-compatible open-source substitutes where they don't:

| Azure service | Local | Notes |
|---|---|---|
| Blob Storage | **Azurite** | Same SDK, `devstoreaccount1` well-known key |
| Cosmos DB (NoSQL) | **Cosmos DB Linux emulator (vNext)** | HTTP on 8081; Data Explorer on 1234 |
| Service Bus | **Service Bus emulator** (+ SQL Server) | Topics/subscriptions declared in `infra/local/servicebus/Config.json` |
| Database for PostgreSQL Flexible Server | `pgvector/pgvector:pg16` | pgvector is supported on the Azure service too |
| Azure Managed Redis | `redis:7` | |
| Communication Services Email | Mailpit | SMTP sink + web UI |
| Monitor / Application Insights | .NET Aspire Dashboard | OTLP traces/logs UI |
| Entra External ID | identity service OTP | See ADR-0009 |
| Key Vault | `.env` file | No emulator; secrets come from Key Vault references in Container Apps |
| API Management / Front Door | gateway service | |

The AI service additionally has `AI_FAKE=true` (offline fake LLM) and `EMBEDDING_PROVIDER=fake`, so
no external API is needed for day-to-day development.

## Consequences
- ➕ Full-stack dev and CI with zero cloud cost; identical SDK code paths.
- ➖ Emulators lag the cloud in features/limits (e.g. Service Bus emulator entity limits; Cosmos vNext
  supports only the NoSQL API). Staging on real Azure remains required before release.
- ➖ Service Bus emulator needs SQL Server (≈2 GB RAM) and currently targets x64 hosts.
- ➖ Emulator credentials are public well-known values — they must never be used against real Azure.

## Revisit when
Emulator gaps block a feature, or Aspire app-host orchestration becomes preferable to compose.

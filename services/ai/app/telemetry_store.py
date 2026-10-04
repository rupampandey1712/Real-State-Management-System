"""AI request log in Azure Cosmos DB (emulator locally). Container `ai-requests`, partition key
/feature, TTL = retention days. Logging never breaks a user request: failures are swallowed + logged.

Document ids look like '<feature>.<hex>' so feedback can locate the partition from the id alone.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient

from app.config import settings
from app.guardrails import redact_pii
from app.pricing import cost_usd_micros

log = structlog.get_logger(__name__)
MAX_PAYLOAD_CHARS = 4000


def _truncate(value: object) -> str:
    return redact_pii(str(value))[:MAX_PAYLOAD_CHARS]


@dataclass
class AIRequestLog:
    id: str
    feature: str
    model: str
    prompt_id: str
    prompt_version: int
    user_id: str | None
    listing_id: str | None
    request: str
    usage: dict = field(default_factory=dict)
    provider_response_id: str | None = None

    @classmethod
    def start(cls, ctx, prompt, model: str | None = None) -> "AIRequestLog":
        return cls(
            id=f"{ctx.feature}.{uuid.uuid4().hex}",
            feature=ctx.feature,
            model=model or prompt.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            user_id=ctx.user_id,
            listing_id=ctx.listing_id,
            request=_truncate(prompt.user),
        )

    def record_usage(self, usage, response_id: str | None) -> None:
        """`usage` is Gemini's `usage_metadata`; any count may be absent (None)."""
        self.provider_response_id = response_id
        if usage is None:
            return
        self.usage = {
            "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
            "thinking_tokens": getattr(usage, "thoughts_token_count", 0) or 0,
            "cached_tokens": getattr(usage, "cached_content_token_count", 0) or 0,
        }


class AIRequestStore:
    def __init__(self) -> None:
        self._client: CosmosClient | None = None
        self._container = None

    async def init(self) -> None:
        if not settings.cosmos_key:
            log.warning("cosmos_not_configured_ai_logging_disabled")
            return
        try:
            self._client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key,
                                        enable_endpoint_discovery=False)
            database = await self._client.create_database_if_not_exists(settings.cosmos_database)
            self._container = await database.create_container_if_not_exists(
                id="ai-requests", partition_key=PartitionKey(path="/feature"),
                default_ttl=settings.ai_log_retention_days * 86400,
            )
        except Exception:
            log.exception("cosmos_init_failed_ai_logging_disabled")
            self._container = None

    async def finish(self, entry: AIRequestLog, started: float, *, status: str, response: object = None,
                     error: str | None = None, stop_reason: str | None = None) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info("ai_request", id=entry.id, feature=entry.feature, model=entry.model, status=status,
                 latency_ms=latency_ms, **entry.usage)
        if self._container is None:
            return
        document = {
            "id": entry.id,
            "feature": entry.feature,
            "model": entry.model,
            "prompt_id": entry.prompt_id,
            "prompt_version": entry.prompt_version,
            "user_id": entry.user_id,
            "listing_id": entry.listing_id,
            "status": status,
            "stop_reason": stop_reason,
            "error": error,
            "latency_ms": latency_ms,
            **entry.usage,
            "cost_usd_micros": cost_usd_micros(entry.model, entry.usage),
            "provider_response_id": entry.provider_response_id,
            "request_redacted": entry.request,
            "response_redacted": _truncate(response) if response is not None else None,
            "feedback": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        try:
            await self._container.upsert_item(document)
        except Exception:
            log.warning("ai_request_log_write_failed", id=entry.id)

    async def set_feedback(self, request_id: str, rating: int, comment: str | None) -> bool:
        if self._container is None:
            return False
        feature = request_id.split(".", 1)[0]
        try:
            item = await self._container.read_item(item=request_id, partition_key=feature)
        except Exception:
            return False
        item["feedback"], item["feedback_comment"] = rating, redact_pii(comment or "")[:1000] or None
        await self._container.replace_item(item=request_id, body=item)
        return True

    @property
    def enabled(self) -> bool:
        return self._container is not None

    async def _query(self, query: str, parameters: list[dict]) -> list[dict]:
        if self._container is None:
            return []
        return [item async for item in self._container.query_items(query=query, parameters=parameters)]

    async def recent(self, days: int) -> list[dict]:
        """Metric fields of every request in the last `days` days (cross-partition; bounded by the TTL)."""
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        return await self._query(
            "SELECT c.feature, c.status, c.created_at, c.latency_ms, c.input_tokens, c.output_tokens, "
            "c.thinking_tokens, c.cost_usd_micros, c.feedback FROM c WHERE c.created_at >= @since",
            [{"name": "@since", "value": since}],
        )

    async def with_feedback(self, rating: int, feature: str | None, limit: int) -> list[dict]:
        query = "SELECT * FROM c WHERE c.feedback = @rating"
        parameters: list[dict] = [{"name": "@rating", "value": rating}]
        if feature:
            query += " AND c.feature = @feature"
            parameters.append({"name": "@feature", "value": feature})
        rows = await self._query(query, parameters)
        return sorted(rows, key=lambda r: r.get("created_at", ""), reverse=True)[:limit]

    async def forget_user(self, user_id: str) -> int:
        """FR-6.4: unlink a deleted account from its AI requests. Content was PII-redacted when logged;
        the rows stay (without the user id) for cost and quality metrics until their TTL expires."""
        if self._container is None:
            return 0
        rows = await self._query("SELECT * FROM c WHERE c.user_id = @u", [{"name": "@u", "value": user_id}])
        for row in rows:
            row["user_id"] = None
            await self._container.replace_item(item=row["id"], body=row)
        return len(rows)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()


ai_log = AIRequestStore()

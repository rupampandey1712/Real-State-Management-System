"""FastAPI app factory shared by all HTTP services: logging, error envelope, telemetry, health."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from estate_common.db import Database
from estate_common.errors import install_error_handling
from estate_common.logging import configure_logging
from estate_common.settings import CommonSettings
from estate_common.telemetry import configure_telemetry

ReadinessCheck = Callable[[], Awaitable[Any]]


def postgres_check(db: Database) -> ReadinessCheck:
    async def check() -> None:
        async with db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    return check


def redis_check(client: redis.Redis) -> ReadinessCheck:
    async def check() -> None:
        await client.ping()
    return check


def create_app(settings: CommonSettings, *, title: str, lifespan: Any = None,
               readiness: dict[str, ReadinessCheck] | None = None) -> FastAPI:
    configure_logging(settings.service_name, settings.log_level)
    app = FastAPI(title=title, lifespan=lifespan, docs_url="/docs" if settings.is_local else None)
    install_error_handling(app)
    configure_telemetry(app, settings.service_name, settings.otel_exporter_otlp_endpoint)
    checks = readiness or {}

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        """Liveness: the process is up."""
        return {"status": "ok", "service": settings.service_name}

    @app.get("/health/ready", tags=["ops"])
    async def ready() -> JSONResponse:
        """Readiness: dependencies answer within 2 s. The gateway's active health checks use this."""
        results: dict[str, str] = {}
        for name, check in checks.items():
            try:
                await asyncio.wait_for(check(), timeout=2)
                results[name] = "ok"
            except Exception as exc:  # report, don't raise
                results[name] = f"fail: {type(exc).__name__}"
        healthy = all(v == "ok" for v in results.values())
        return JSONResponse(status_code=200 if healthy else 503,
                            content={"status": "ready" if healthy else "not_ready", "checks": results})

    return app

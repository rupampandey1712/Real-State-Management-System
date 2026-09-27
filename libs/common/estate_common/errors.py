"""Domain exceptions and the error envelope (docs/design.md §3.1) — global exception handling."""

import time
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = structlog.get_logger(__name__)


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class NotFound(DomainError):
    status_code, code = 404, "not_found"


class Unauthorized(DomainError):
    status_code, code = 401, "unauthorized"


class Forbidden(DomainError):
    status_code, code = 403, "forbidden"


class Conflict(DomainError):
    status_code, code = 409, "conflict"


class ValidationFailed(DomainError):
    status_code, code = 422, "validation_error"


class AIUnavailable(DomainError):
    status_code, code = 503, "ai_unavailable"


class DependencyUnavailable(DomainError):
    """A downstream service is down, timing out, or its circuit breaker is open."""

    status_code, code = 503, "dependency_unavailable"


def envelope(request_id: str, status: int, code: str, message: str, details: list | None = None,
             headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or [], "request_id": request_id}},
        headers={"X-Request-Id": request_id, **(headers or {})},
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def install_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        incoming = request.headers.get("X-Request-Id", "")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            if not request.url.path.startswith("/health"):
                # One line per request: the anchor for tracing a request through the logs.
                log.info("request", method=request.method, path=request.url.path, status=status,
                         duration_ms=round((time.perf_counter() - started) * 1000, 1))
            structlog.contextvars.unbind_contextvars("request_id")

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        headers = {"Retry-After": "10"} if exc.status_code == 503 else None
        return envelope(_request_id(request), exc.status_code, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "issue": e["type"]} for e in exc.errors()]
        return envelope(_request_id(request), 422, "validation_error", "Request validation failed.", details)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("unhandled_error", path=request.url.path)
        return envelope(_request_id(request), 500, "internal", "Something went wrong.")

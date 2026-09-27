"""Client for the AI service's internal endpoints, with retries + circuit breaker (estate_common.http).

Both endpoints are pure functions of their input, so POST retries are safe (idempotent=True).
Query parsing gets no retries — it runs inside the 2 s NL-search budget and falls back instead.
"""

from app.config import settings
from estate_common.errors import DependencyUnavailable
from estate_common.http import ResilientClient


class AIClient:
    def __init__(self) -> None:
        self._http = ResilientClient("ai", settings.ai_url, settings=settings, timeout=30)

    async def embed(self, texts: list[str], input_type: str, timeout: float = 30.0) -> list[list[float]]:
        response = await self._http.post("/internal/embeddings", json={"texts": texts, "input_type": input_type},
                                         timeout=timeout, idempotent=True)
        if response.status_code >= 400:
            raise DependencyUnavailable("Embeddings are unavailable.")
        return response.json()["vectors"]

    async def parse_query(self, query: str, timeout: float) -> dict:
        response = await self._http.post("/internal/nl-parse", json={"query": query}, timeout=timeout, idempotent=False)
        if response.status_code >= 400:
            raise DependencyUnavailable("Query parsing is unavailable.")
        return response.json()

    async def close(self) -> None:
        await self._http.aclose()

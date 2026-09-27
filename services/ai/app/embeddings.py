"""Embedding providers behind one interface (ADR-0003)."""

import hashlib
import math
import re
from functools import lru_cache
from typing import Literal, Protocol

from app.config import settings

InputType = Literal["document", "query"]


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]: ...


class HashingEmbeddings:
    """Offline, deterministic lexical embeddings (hashing trick over words + bigrams).
    Good enough to exercise the pipeline locally; not a quality stand-in for real embeddings."""

    model = "hashing-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        features = words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
        vector = [0.0] * self.dim
        for feature in features:
            digest = hashlib.md5(feature.encode()).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class GeminiEmbeddings:
    """gemini-embedding-001 via the Google Gen AI SDK. Outputs below 3072 dimensions are not
    normalised by the API, so we L2-normalise them (cosine distance assumes unit vectors)."""

    BATCH = 100
    TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}

    def __init__(self, api_key: str, model: str, dim: int):
        from google import genai

        self.model = model
        self._dim = dim
        self._client = genai.Client(api_key=api_key or None)

    async def embed(self, texts: list[str], input_type: InputType) -> list[list[float]]:
        from google.genai import types

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            result = await self._client.aio.models.embed_content(
                model=self.model,
                contents=texts[start : start + self.BATCH],
                config=types.EmbedContentConfig(task_type=self.TASK_TYPES[input_type], output_dimensionality=self._dim),
            )
            vectors.extend(_normalise(e.values) for e in result.embeddings)
        return vectors


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


@lru_cache
def get_embedder() -> EmbeddingProvider:
    if settings.embedding_provider == "gemini":
        return GeminiEmbeddings(settings.gemini_api_key, settings.embedding_model, settings.embedding_dim)
    return HashingEmbeddings(settings.embedding_dim)

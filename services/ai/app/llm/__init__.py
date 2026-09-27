from functools import lru_cache

from app.config import settings
from app.llm.base import LLMClient


@lru_cache
def get_llm() -> LLMClient:
    if settings.ai_fake:
        from app.llm.fake import FakeLLMClient

        return FakeLLMClient()
    from app.llm.gemini_client import GeminiLLMClient

    return GeminiLLMClient()

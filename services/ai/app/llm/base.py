"""LLM gateway contract (ADR-0004). Feature code depends on this protocol, never on the SDK."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.prompts.loader import RenderedPrompt

T = TypeVar("T", bound=BaseModel)


class AIRefused(Exception):
    """The model declined the request (stop_reason == 'refusal')."""


class AIOutputInvalid(Exception):
    """The model's structured output was missing or failed validation."""


@dataclass
class CallContext:
    feature: str  # nl_search | describe | improve | qa
    user_id: str | None = None
    listing_id: str | None = None


@dataclass
class Parsed[T]:
    output: T
    request_id: str


@dataclass
class StreamResult:
    """Filled in by LLMClient.stream() once the stream finishes."""

    request_id: str = ""
    stop_reason: str | None = None
    text: str = ""
    extra: dict = field(default_factory=dict)


class LLMClient(Protocol):
    async def parse(self, prompt: RenderedPrompt, output_model: type[T], ctx: CallContext) -> Parsed[T]: ...

    def stream(
        self, prompt: RenderedPrompt, history: list[dict], ctx: CallContext, result: StreamResult
    ) -> AsyncIterator[str]: ...

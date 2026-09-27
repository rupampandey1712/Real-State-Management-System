"""Versioned prompt files: <id>.v<N>.md with YAML front-matter, '# System' and '# User' sections.
See docs/ai/prompts.md for the format and change process."""

import html
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from app.config import settings

PROMPT_DIR = Path(__file__).parent


def untrusted(value: Any) -> str:
    """Neutralise tag-like content in untrusted text so it can't close our XML delimiters."""
    return html.escape(str(value or ""), quote=False)


_env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
_env.filters["untrusted"] = untrusted


@dataclass(frozen=True)
class PromptTemplate:
    id: str
    version: int
    model_config_key: str
    max_tokens: int
    thinking_level: str | None
    system: str
    user: str


@dataclass
class RenderedPrompt:
    id: str
    version: int
    model: str
    max_tokens: int
    thinking_level: str | None
    system: str
    user: str
    variables: dict[str, Any] = field(default_factory=dict)


@lru_cache
def load(prompt_id: str, version: int) -> PromptTemplate:
    text = (PROMPT_DIR / f"{prompt_id}.v{version}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    system, user = body.split("# User", 1)
    system = system.split("# System", 1)[1]
    if meta["id"] != prompt_id or meta["version"] != version:
        raise ValueError(f"Prompt front-matter mismatch in {prompt_id}.v{version}.md")
    return PromptTemplate(
        id=prompt_id, version=version, model_config_key=meta["model_config_key"],
        max_tokens=int(meta["max_tokens"]), thinking_level=meta.get("thinking_level"),
        system=system.strip(), user=user.strip(),
    )


def render(prompt_id: str, **variables: Any) -> RenderedPrompt:
    version = getattr(settings, f"ai_prompt_version_{prompt_id}", 1)
    template = load(prompt_id, version)
    return RenderedPrompt(
        id=template.id,
        version=template.version,
        model=settings.model_for(template.model_config_key),
        max_tokens=template.max_tokens,
        thinking_level=template.thinking_level,
        system=_env.from_string(template.system).render(**variables),
        user=_env.from_string(template.user).render(**variables),
        variables=variables,
    )

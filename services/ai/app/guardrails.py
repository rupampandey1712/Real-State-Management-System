"""Deterministic guardrails (docs/ai/guardrails.md). Prompts are one layer; these checks are another."""

import re
import unicodedata

# ── Input ─────────────────────────────────────────────────────────────────────
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
AADHAAR = re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")
CONTROL = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f​-‏ - ﻿]")


def sanitize(text: str, max_chars: int) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = CONTROL.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def redact_pii(text: str) -> str:
    text = EMAIL.sub("[REDACTED_EMAIL]", text)
    text = AADHAAR.sub("[REDACTED_ID]", text)
    text = PHONE.sub("[REDACTED_PHONE]", text)
    return PAN.sub("[REDACTED_ID]", text)


ADVICE = re.compile(
    r"\b(good investment|worth (buying|investing)|(will|would) (the )?(price|value)s? (go up|increase|appreciate)|"
    r"roi|return on investment|appreciation|title (is )?clear|legal(ly)? (safe|advice)|tax (benefit|saving)s?)\b",
    re.I,
)


def screen_intent(question: str) -> str | None:
    """Rule-based pre-screen for Q&A. Returns 'advice' for legal/tax/investment questions."""
    return "advice" if ADVICE.search(question) else None


# ── Fair housing (see docs/ai/guardrails.md §4) ──────────────────────────────
PROTECTED = re.compile(
    r"\b(veg(etarian)?s?|non[- ]?veg(etarian)?|jain|hindu|muslim|christian|sikh|parsi|brahmin|caste|"
    r"community|bachelors?|spinsters?|family only|families only|married (couples? )?only|"
    r"north indians?|south indians?|foreigners?|religion|religious)\b",
    re.I,
)
EXCLUSION_CONTEXT = re.compile(r"\b(only|not allowed|no|ideal for|suitable for|preferred|perfect for|strictly)\b", re.I)


def mentions_protected(text: str) -> bool:
    return bool(PROTECTED.search(text))


def fair_housing_violations(text: str) -> list[str]:
    """Sentences that combine a protected characteristic with preference/exclusion language."""
    violations = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if PROTECTED.search(sentence) and EXCLUSION_CONTEXT.search(sentence):
            violations.append(sentence.strip())
    return violations


# ── Output ────────────────────────────────────────────────────────────────────
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}


def unsupported_numbers(output: str, source: str) -> list[str]:
    """Numbers in generated copy that don't appear anywhere in the source facts."""
    allowed = _numbers(source)
    return sorted(n for n in _numbers(output) if n not in allowed)


CITATION = re.compile(r"\[([SD]\d+)\]")


def invalid_citations(answer: str, valid_ids: set[str]) -> list[str]:
    return sorted({c for c in CITATION.findall(answer) if c not in valid_ids})


def citations_in(answer: str) -> list[str]:
    return list(dict.fromkeys(CITATION.findall(answer)))


UNKNOWN = re.compile(r"(don't|do not) have (that|this) information", re.I)


def is_unknown_answer(answer: str) -> bool:
    return bool(UNKNOWN.search(answer))

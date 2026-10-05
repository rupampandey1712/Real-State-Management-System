"""Grounded listing Q&A — RAG scoped to one listing (FR-5, docs/design.md §4.5)."""

import json
from collections.abc import AsyncIterator

from sqlalchemy import select

from app import guardrails
from app.config import settings
from app.embeddings import get_embedder
from app.llm import get_llm
from app.llm.base import CallContext, StreamResult
from app.models import DocumentChunk
from app.prompts.loader import render
from estate_common.db import Database

MAX_QUESTION_CHARS = 1000
ADVICE_TEMPLATE = (
    "I can't give legal, tax or investment advice. A qualified professional can help with that. "
    "I'm happy to answer questions about what this listing includes."
)
UNAVAILABLE_TEMPLATE = "The assistant is unavailable right now. You can still contact the agent."

SUGGESTIONS = [
    ("Maintenance per month", "What's the monthly maintenance?"),
    ("Covered parking", "Is parking included?"),
    ("Pets", "Are pets allowed?"),
    ("Furnishing", "What furnishing is included?"),
    ("Possession", "When is possession?"),
    ("Floor", "Which floor is it on?"),
]


def suggestions(facts: list[dict], has_documents: bool) -> list[str]:
    labels = {f["label"] for f in facts}
    items = [question for label, question in SUGGESTIONS if label in labels][:3]
    if has_documents:
        items.append("What do the society rules say?")
    return items


async def retrieve_chunks(db: Database, listing_id: str, question: str) -> list[dict]:
    [query_vector] = await get_embedder().embed([question], input_type="query")
    distance = DocumentChunk.embedding.cosine_distance(query_vector)
    async with db.sessionmaker() as session:
        rows = (
            await session.execute(
                select(DocumentChunk, distance.label("distance"))
                .where(DocumentChunk.listing_id == listing_id)  # isolation: never cross listings
                .order_by(distance)
                .limit(settings.qa_top_k_chunks)
            )
        ).all()
    documents = []
    for index, (chunk, _distance) in enumerate(r for r in rows if 1 - r[1] >= settings.qa_min_similarity):
        pages = f"{chunk.page_from}" if chunk.page_from == chunk.page_to else f"{chunk.page_from}-{chunk.page_to}"
        documents.append({"id": f"D{index + 1}", "filename": chunk.filename, "pages": pages, "content": chunk.content})
    return documents


def clean_history(history: list[dict]) -> list[dict]:
    turns = [
        {"role": h["role"], "content": guardrails.redact_pii(guardrails.sanitize(str(h.get("content", "")), 2000))}
        for h in history
        if h.get("role") in {"user", "assistant"} and h.get("content")
    ][-settings.qa_max_history_turns * 2 :]
    while turns and turns[0]["role"] != "user":  # conversation must start with a user turn
        turns.pop(0)
    while turns and turns[-1]["role"] != "assistant":  # the new question is appended as the next user turn
        turns.pop()
    return turns


EXCERPT_CHARS = 400


def _excerpt(content: str) -> str:
    text = " ".join(content.split())
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


async def answer(db: Database, facts_payload: dict, question: str, history: list[dict], ctx: CallContext) -> AsyncIterator[dict]:
    """Yields SSE events: token*, citations, done | error."""
    question = guardrails.redact_pii(guardrails.sanitize(question, MAX_QUESTION_CHARS))
    if guardrails.screen_intent(question) == "advice":
        yield _sse("token", {"text": ADVICE_TEMPLATE})
        yield _sse("citations", {"sources": []})
        yield _sse("done", {"ai_request_id": None, "answer_status": "refused"})
        return

    facts = facts_payload["facts"]
    try:
        documents = await retrieve_chunks(db, ctx.listing_id, question)
    except Exception:
        documents = []  # degrade to facts-only answers if embeddings are down
    prompt = render("qa", facts=facts, documents=documents, question=question)
    result = StreamResult()
    try:
        async for text in get_llm().stream(prompt, clean_history(history), ctx, result):
            yield _sse("token", {"text": text})
    except Exception:
        yield _sse("error", {"code": "ai_unavailable", "message": UNAVAILABLE_TEMPLATE})
        return

    # FR-5.2: citations are clickable — a field shows its value, a document shows the passage it came from.
    sources = {f["id"]: {"id": f["id"], "type": "listing_field", "label": f["label"], "excerpt": f["value"]} for f in facts}
    sources |= {d["id"]: {"id": d["id"], "type": "document", "label": f"{d['filename']}, p.{d['pages']}",
                          "excerpt": _excerpt(d["content"])} for d in documents}
    invalid = guardrails.invalid_citations(result.text, set(sources))
    cited = [sources[c] for c in guardrails.citations_in(result.text) if c in sources]

    if result.stop_reason == "refusal":
        status = "refused"
    elif guardrails.is_unknown_answer(result.text):
        status = "unknown"
    elif not cited or invalid:
        status = "unverified"
    else:
        status = "answered"
    yield _sse("citations", {"sources": cited, "invalid": invalid})
    yield _sse("done", {"ai_request_id": result.request_id, "answer_status": status})

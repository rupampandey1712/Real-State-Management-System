"""Document ingestion: listing.document_uploaded → PDF text → chunks → embeddings → pgvector.
The ai.document_processed event is written to the outbox in the same transaction as the chunks (ADR-0016)."""

import io
import re

import structlog
from azure.storage.blob.aio import BlobServiceClient
from fastapi.concurrency import run_in_threadpool
from pypdf import PdfReader
from sqlalchemy import delete

from app.config import settings
from app.embeddings import get_embedder
from app.models import DocumentChunk
from estate_common import events
from estate_common.db import Database
from estate_common.events import Event
from estate_common.outbox import add_event

log = structlog.get_logger(__name__)

TARGET_WORDS = 450  # ≈ 600 tokens
OVERLAP_WORDS = 60
MAX_PAGES = 100


def extract_pages(data: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(data))
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"Document has more than {MAX_PAGES} pages.")
    return [re.sub(r"[ \t]+", " ", page.extract_text() or "").strip() for page in reader.pages]


def chunk_pages(pages: list[str]) -> list[tuple[int, int, str]]:
    """Returns (page_from, page_to, text) chunks of ~TARGET_WORDS words with overlap."""
    words: list[tuple[int, str]] = [(n, w) for n, text in enumerate(pages, start=1) for w in text.split()]
    chunks, start = [], 0
    while start < len(words):
        window = words[start : start + TARGET_WORDS]
        chunks.append((window[0][0], window[-1][0], " ".join(w for _, w in window)))
        if start + TARGET_WORDS >= len(words):
            break
        start += TARGET_WORDS - OVERLAP_WORDS
    return chunks


class DocumentIngestor:
    def __init__(self, db: Database):
        self._db = db
        self._blobs = BlobServiceClient.from_connection_string(settings.storage_connection)

    async def handle(self, event: Event) -> None:
        data = event.data
        try:
            blob = self._blobs.get_blob_client(settings.media_container, data["storage_key"])
            raw = await (await blob.download_blob()).readall()
            pages = await run_in_threadpool(extract_pages, raw)
            chunks = chunk_pages(pages)
            if not chunks:
                raise ValueError("No extractable text found (scanned PDFs are not supported yet).")
            embedder = get_embedder()
            vectors = await embedder.embed([text for _, _, text in chunks], input_type="document")
            async with self._db.sessionmaker() as session:
                # Idempotent: a redelivered event replaces the chunks instead of duplicating them.
                await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == data["document_id"]))
                session.add_all(
                    DocumentChunk(
                        document_id=data["document_id"], listing_id=data["listing_id"], filename=data["filename"],
                        chunk_index=i, page_from=p_from, page_to=p_to, content=text,
                        token_estimate=int(len(text.split()) * 1.3), embedding=vector, embedding_model=embedder.model,
                    )
                    for i, ((p_from, p_to, text), vector) in enumerate(zip(chunks, vectors, strict=True))
                )
                self._stage_status(session, data, "ready", None)
                await session.commit()
            log.info("document_ingested", document_id=data["document_id"], chunks=len(chunks))
        except ValueError as exc:
            async with self._db.sessionmaker() as session:
                self._stage_status(session, data, "failed", str(exc))
                await session.commit()
        except Exception:
            log.exception("document_ingestion_failed", document_id=data["document_id"])
            raise  # let Service Bus retry; dead-letters after MaxDeliveryCount

    @staticmethod
    def _stage_status(session, data: dict, status: str, error: str | None) -> None:
        add_event(session, topic=events.AI_EVENTS, event_type=events.DOCUMENT_PROCESSED, subject=data["listing_id"],
                  source="ai", data={"document_id": data["document_id"], "listing_id": data["listing_id"],
                                     "status": status, "error": error})

"""Search read model — a denormalised projection of published listings, built from
listing-events. The search service owns this data; it is never written by other services."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, DateTime, Float, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR, UUID  # postgresql.ARRAY supports @> (contains)
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from estate_common.db import Base


class SearchListing(Base):
    __tablename__ = "search_listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    listing_type: Mapped[str] = mapped_column(String(4))
    property_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    bedrooms: Mapped[int] = mapped_column(SmallInteger)
    bathrooms: Mapped[int | None] = mapped_column(SmallInteger)
    carpet_area_sqft: Mapped[int | None] = mapped_column(Integer)
    furnishing: Mapped[str | None] = mapped_column(String(16))
    pet_policy: Mapped[str] = mapped_column(String(12), default="unknown")
    amenities: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    locality: Mapped[str] = mapped_column(String(80))
    city: Mapped[str] = mapped_column(String(40))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    thumbnail_key: Mapped[str | None] = mapped_column(String(300))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))
    search_text = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', title || ' ' || description || ' ' || locality || ' ' || city)", persisted=True),
    )

    __table_args__ = (
        Index("ix_search_filters", "city", "listing_type", "bedrooms", "price_minor"),
        Index("ix_search_fts", "search_text", postgresql_using="gin"),
        Index("ix_search_amenities", "amenities", postgresql_using="gin"),
        Index("ix_search_geo", "lat", "lng"),
        Index(
            "ix_search_embedding", "embedding", postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


def embedding_text(data: dict) -> str:
    """Text embedded for semantic search (docs/design.md §2.3)."""
    amenities = ", ".join(a.replace("_", " ") for a in data.get("amenities", []))
    return (
        f"{data['property_type'].replace('_', ' ')} {data['bedrooms']}BHK for {data['listing_type']} in "
        f"{data['locality']}, {data['city']}. {data['title']}. {data.get('description', '')} Amenities: {amenities}."
    )

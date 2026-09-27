import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from estate_common.db import Base
from estate_common.outbox import OutboxMessage  # noqa: F401 — registers the outbox table for migrations


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(12), default="draft", index=True)  # draft|published|unpublished|archived
    listing_type: Mapped[str] = mapped_column(String(4))  # sale | rent
    property_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    description_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    price_minor: Mapped[int] = mapped_column(BigInteger)
    deposit_minor: Mapped[int | None] = mapped_column(BigInteger)
    maintenance_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    bedrooms: Mapped[int] = mapped_column(SmallInteger)
    bathrooms: Mapped[int | None] = mapped_column(SmallInteger)
    balconies: Mapped[int | None] = mapped_column(SmallInteger)
    carpet_area_sqft: Mapped[int | None] = mapped_column(Integer)
    builtup_area_sqft: Mapped[int | None] = mapped_column(Integer)
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    total_floors: Mapped[int | None] = mapped_column(SmallInteger)
    facing: Mapped[str | None] = mapped_column(String(12))
    furnishing: Mapped[str | None] = mapped_column(String(16))
    parking_covered: Mapped[int] = mapped_column(SmallInteger, default=0)
    parking_open: Mapped[int] = mapped_column(SmallInteger, default=0)
    pet_policy: Mapped[str] = mapped_column(String(12), default="unknown")
    possession: Mapped[str | None] = mapped_column(String(20))  # 'ready_to_move' or ISO date
    amenities: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    address_line: Mapped[str] = mapped_column(String(200))
    locality: Mapped[str] = mapped_column(String(80), index=True)
    city: Mapped[str] = mapped_column(String(40), index=True)
    pincode: Mapped[str | None] = mapped_column(String(6))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    rera_id: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    images: Mapped[list["ListingImage"]] = relationship(
        back_populates="listing", order_by="ListingImage.position", lazy="selectin", cascade="all, delete-orphan"
    )
    documents: Mapped[list["ListingDocument"]] = relationship(
        back_populates="listing", lazy="selectin", cascade="all, delete-orphan"
    )


class ListingImage(Base):
    __tablename__ = "listing_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(300))
    thumb_key: Mapped[str] = mapped_column(String(300))
    caption: Mapped[str | None] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(SmallInteger)
    listing: Mapped[Listing] = relationship(back_populates="images")


class ListingDocument(Base):
    __tablename__ = "listing_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="other")  # floor_plan|society_rules|brochure|other
    status: Mapped[str] = mapped_column(String(12), default="uploaded")  # uploaded|processing|ready|failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    listing: Mapped[Listing] = relationship(back_populates="documents")

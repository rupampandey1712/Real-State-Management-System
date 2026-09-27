import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ListingType = Literal["sale", "rent"]
PropertyType = Literal["apartment", "independent_house", "villa", "plot", "commercial"]
Furnishing = Literal["unfurnished", "semi_furnished", "fully_furnished"]
PetPolicy = Literal["allowed", "not_allowed", "unknown"]
Facing = Literal["north", "south", "east", "west", "north_east", "north_west", "south_east", "south_west"]

# Controlled vocabulary — keep in sync with services/ai/app/features/nl_search.py AMENITIES.
AMENITIES = [
    "lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
    "children_play_area", "gated", "park", "ev_charging", "intercom", "rainwater_harvesting",
]
Amenity = Literal[
    "lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
    "children_play_area", "gated", "park", "ev_charging", "intercom", "rainwater_harvesting",
]


class ListingFields(BaseModel):
    listing_type: ListingType
    property_type: PropertyType
    title: str = Field(min_length=10, max_length=120)
    description: str | None = Field(default=None, max_length=5000)
    description_ai: bool = False
    price_inr: int = Field(gt=0, description="Sale price, or monthly rent, in rupees")
    deposit_inr: int | None = Field(default=None, ge=0)
    maintenance_inr: int | None = Field(default=None, ge=0)
    bedrooms: int = Field(ge=0, le=20)
    bathrooms: int | None = Field(default=None, ge=0, le=20)
    balconies: int | None = Field(default=None, ge=0, le=10)
    carpet_area_sqft: int | None = Field(default=None, gt=0, le=100_000)
    builtup_area_sqft: int | None = Field(default=None, gt=0, le=100_000)
    floor: int | None = Field(default=None, ge=-2, le=200)
    total_floors: int | None = Field(default=None, ge=0, le=200)
    facing: Facing | None = None
    furnishing: Furnishing | None = None
    parking_covered: int = Field(default=0, ge=0, le=10)
    parking_open: int = Field(default=0, ge=0, le=10)
    pet_policy: PetPolicy = "unknown"
    possession: str | None = Field(default=None, max_length=20)
    amenities: list[Amenity] = []
    address_line: str = Field(min_length=3, max_length=200)
    locality: str = Field(min_length=2, max_length=80)
    city: str = Field(min_length=2, max_length=40)
    pincode: str | None = Field(default=None, pattern=r"^\d{6}$")
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    rera_id: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def check_areas(self):
        if self.carpet_area_sqft and self.builtup_area_sqft and self.carpet_area_sqft > self.builtup_area_sqft:
            raise ValueError("Carpet area cannot exceed built-up area.")
        return self


class ListingCreate(ListingFields):
    pass


class ListingUpdate(BaseModel):
    """All fields optional; validated against ListingFields after merge."""

    model_config = {"extra": "forbid"}

    listing_type: ListingType | None = None
    property_type: PropertyType | None = None
    title: str | None = None
    description: str | None = None
    description_ai: bool | None = None
    price_inr: int | None = None
    deposit_inr: int | None = None
    maintenance_inr: int | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    balconies: int | None = None
    carpet_area_sqft: int | None = None
    builtup_area_sqft: int | None = None
    floor: int | None = None
    total_floors: int | None = None
    facing: Facing | None = None
    furnishing: Furnishing | None = None
    parking_covered: int | None = None
    parking_open: int | None = None
    pet_policy: PetPolicy | None = None
    possession: str | None = None
    amenities: list[Amenity] | None = None
    address_line: str | None = None
    locality: str | None = None
    city: str | None = None
    pincode: str | None = None
    lat: float | None = None
    lng: float | None = None
    rera_id: str | None = None


class Money(BaseModel):
    amount_minor: int
    currency: str
    display: str


class ImageOut(BaseModel):
    id: uuid.UUID
    url: str
    thumb_url: str
    caption: str | None
    position: int


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    kind: str
    status: str
    error: str | None
    created_at: datetime


class ListingOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    listing_type: str
    property_type: str
    title: str
    description: str | None
    description_ai: bool
    price: Money
    deposit: Money | None
    maintenance: Money | None
    bedrooms: int
    bathrooms: int | None
    balconies: int | None
    carpet_area_sqft: int | None
    builtup_area_sqft: int | None
    floor: int | None
    total_floors: int | None
    facing: str | None
    furnishing: str | None
    parking_covered: int
    parking_open: int
    pet_policy: str
    possession: str | None
    amenities: list[str]
    address_line: str
    locality: str
    city: str
    pincode: str | None
    lat: float | None
    lng: float | None
    rera_id: str | None
    images: list[ImageOut]
    published_at: datetime | None
    updated_at: datetime


class ListingSummary(BaseModel):
    id: uuid.UUID
    status: str
    title: str
    price: Money
    bedrooms: int
    locality: str
    city: str
    thumbnail_url: str | None
    documents_count: int
    updated_at: datetime

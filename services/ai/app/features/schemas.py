"""Structured-output models. Their JSON schema is sent as Gemini's `response_json_schema` and the
reply is validated with Pydantic, so every field is required-but-nullable: the model always emits
every key, and code never guesses defaults."""

from typing import Literal

from pydantic import BaseModel, Field

City = Literal["Pune", "Bengaluru", "Mumbai"]
PropertyType = Literal["apartment", "independent_house", "villa", "plot", "commercial"]
Furnishing = Literal["unfurnished", "semi_furnished", "fully_furnished"]
Amenity = Literal[
    "lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
    "children_play_area", "gated", "park", "ev_charging", "intercom", "rainwater_harvesting",
]
Near = Literal["metro", "school", "hospital", "it_park", "mall", "railway_station", "airport"]

SUPPORTED_CITIES = ["Pune", "Bengaluru", "Mumbai"]


class SearchFilters(BaseModel):
    is_property_query: bool
    city: City | None
    locality: str | None
    listing_type: Literal["sale", "rent"] | None
    property_type: PropertyType | None
    bedrooms_min: int | None
    bedrooms_max: int | None
    price_min_inr: int | None = Field(description="Whole rupees")
    price_max_inr: int | None = Field(description="Whole rupees")
    furnishing: Furnishing | None
    pet_policy: Literal["allowed"] | None
    amenities: list[Amenity]
    near: list[Near]
    soft_preferences: list[str]
    assumptions: list[str]

    @classmethod
    def empty(cls, **values) -> "SearchFilters":
        base = {name: None for name in cls.model_fields} | {
            "is_property_query": True, "amenities": [], "near": [], "soft_preferences": [], "assumptions": [],
        }
        return cls(**(base | values))


class DescribeOutput(BaseModel):
    title: str = Field(description="At most 80 characters")
    description: str
    highlights: list[str] = Field(description="3 to 6 short factual phrases")


class ImproveOutput(BaseModel):
    description: str

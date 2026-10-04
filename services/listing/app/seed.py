"""Synthetic sample listings for local development (no real data, no scraping).

Run:  docker compose exec listing python -m app.seed 60
"""

import asyncio
import random
import sys
import uuid
from datetime import UTC, datetime

from app.config import settings
from app.mapping import to_snapshot
from app.models import Listing
from estate_common import events
from estate_common.db import Database
from estate_common.http import ResilientClient
from estate_common.outbox import add_event

LOCALITIES = {
    "Pune": [("Kharadi", 18.5515, 73.9348), ("Baner", 18.5590, 73.7868), ("Hinjewadi", 18.5912, 73.7389),
             ("Wakad", 18.5987, 73.7688), ("Viman Nagar", 18.5679, 73.9143), ("Kothrud", 18.5074, 73.8077)],
    "Bengaluru": [("Koramangala", 12.9352, 77.6245), ("Indiranagar", 12.9784, 77.6408), ("Whitefield", 12.9698, 77.7500),
                  ("HSR Layout", 12.9116, 77.6474), ("Hebbal", 13.0358, 77.5970)],
    "Mumbai": [("Andheri West", 19.1364, 72.8296), ("Powai", 19.1176, 72.9060), ("Bandra West", 19.0596, 72.8295),
               ("Thane West", 19.2183, 72.9781), ("Goregaon East", 19.1663, 72.8526)],
}
FEATURES = ["park-facing balcony", "large windows with good natural light", "quiet internal road",
            "modular kitchen", "wooden flooring in bedrooms", "recently repainted", "corner unit with cross ventilation"]
AMENITY_POOL = ["lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
                "children_play_area", "gated", "park", "ev_charging", "intercom"]


def _price(city: str, bedrooms: int, rent: bool) -> int:
    base = {"Mumbai": 1.8, "Bengaluru": 1.2, "Pune": 1.0}[city]
    if rent:
        return int(round(base * bedrooms * random.randint(9_000, 14_000), -3))
    return int(round(base * bedrooms * random.randint(3_200_000, 4_800_000), -5))


def make_listing(agent_id: uuid.UUID) -> Listing:
    city = random.choice(list(LOCALITIES))
    locality, lat, lng = random.choice(LOCALITIES[city])
    rent = random.random() < 0.35
    bedrooms = random.choice([1, 2, 2, 2, 3, 3, 4])
    carpet = bedrooms * random.randint(380, 520)
    feature = random.choice(FEATURES)
    furnishing = random.choice(["unfurnished", "semi_furnished", "fully_furnished"])
    total_floors = random.randint(4, 30)
    listing = Listing(
        agent_id=agent_id,
        status="published",
        listing_type="rent" if rent else "sale",
        property_type="apartment" if random.random() < 0.85 else "villa",
        title=f"{bedrooms} BHK {'for rent' if rent else 'apartment'} in {locality} with {feature.split(' with ')[0]}"[:120],
        description=(
            f"A {furnishing.replace('_', ' ')} {bedrooms} BHK home in {locality}, {city}, with {carpet} sq ft carpet area. "
            f"Highlights include a {feature}. Located on floor {min(total_floors, random.randint(1, total_floors))} "
            f"of {total_floors}."
        ),
        price_minor=_price(city, bedrooms, rent) * 100,
        deposit_minor=(_price(city, bedrooms, rent) * 4 * 100) if rent else None,
        maintenance_minor=random.choice([2500, 3500, 4500, 6000]) * 100,
        bedrooms=bedrooms,
        bathrooms=max(1, bedrooms - random.choice([0, 0, 1])),
        balconies=random.randint(0, 2),
        carpet_area_sqft=carpet,
        builtup_area_sqft=int(carpet * 1.2),
        floor=random.randint(1, total_floors),
        total_floors=total_floors,
        facing=random.choice(["north", "east", "west", "south", "north_east"]),
        furnishing=furnishing,
        parking_covered=random.choice([0, 1, 1, 2]),
        parking_open=random.choice([0, 0, 1]),
        pet_policy=random.choice(["allowed", "not_allowed", "unknown"]),
        possession="ready_to_move",
        property_age_years=random.randint(0, 15),
        amenities=random.sample(AMENITY_POOL, k=random.randint(2, 6)),
        address_line=f"Sample Residency, Tower {random.choice('ABCD')}",
        locality=locality,
        city=city,
        pincode={"Pune": "4110", "Bengaluru": "5600", "Mumbai": "4000"}[city] + f"{random.randint(1, 99):02d}",
        lat=lat + random.uniform(-0.01, 0.01),
        lng=lng + random.uniform(-0.01, 0.01),
        published_at=datetime.now(UTC),
    )
    listing.images = []
    listing.documents = []
    return listing


async def seed(db: Database, count: int) -> int:
    identity = ResilientClient("identity", settings.identity_url, settings=settings, timeout=10)
    try:
        response = (await identity.get("/internal/users/by-email/agent@example.com")).raise_for_status()
        agent_id = uuid.UUID(response.json()["id"])
    finally:
        await identity.aclose()

    async with db.sessionmaker() as session:
        created = [make_listing(agent_id) for _ in range(count)]
        session.add_all(created)
        await session.flush()
        for listing in created:  # events go out via the outbox relay, in the same transaction
            add_event(session, topic=events.LISTING_EVENTS, event_type=events.LISTING_PUBLISHED,
                      subject=str(listing.id), data=to_snapshot(listing), source="listing-seed")
        await session.commit()
    return len(created)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    database = Database(settings.database_url)

    async def _main() -> None:
        print(f"Created {await seed(database, n)} listings (events queued in the outbox)")

    asyncio.run(_main())

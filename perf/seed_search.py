"""Bulk-load synthetic listings straight into the search read model for load tests (T1.15, NFR-9).

Going through the listing service would push 100k events through the Service Bus emulator, which takes
hours; the load test measures the search service, so we load its read model directly. Rows are marked
with a `[perf]` title prefix and removed with --clean. Embeddings are left NULL: classic search (the
p95 < 300 ms target) doesn't use them, and NL search needs a real model to be meaningful.

    python perf/seed_search.py --count 100000            # postgres on localhost:5432 (docker compose)
    python perf/seed_search.py --clean
"""

import argparse
import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg

DSN = "postgresql://estate:estate@localhost:5432/search"
CITIES = {
    "Pune": [("Kharadi", 18.5515, 73.9348), ("Baner", 18.5590, 73.7868), ("Hinjewadi", 18.5912, 73.7389),
             ("Wakad", 18.5987, 73.7688), ("Viman Nagar", 18.5679, 73.9143), ("Kothrud", 18.5074, 73.8077)],
    "Bengaluru": [("Koramangala", 12.9352, 77.6245), ("Indiranagar", 12.9784, 77.6408), ("Whitefield", 12.9698, 77.7500),
                  ("HSR Layout", 12.9116, 77.6474), ("Hebbal", 13.0358, 77.5970)],
    "Mumbai": [("Andheri West", 19.1364, 72.8296), ("Powai", 19.1176, 72.9060), ("Bandra West", 19.0596, 72.8295),
               ("Thane West", 19.2183, 72.9781), ("Goregaon East", 19.1663, 72.8526)],
}
AMENITIES = ["lift", "gym", "swimming_pool", "power_backup", "security_24x7", "club_house",
             "children_play_area", "gated", "park", "ev_charging", "intercom"]
COLUMNS = ["id", "listing_type", "property_type", "title", "description", "price_minor", "currency", "bedrooms",
           "bathrooms", "carpet_area_sqft", "furnishing", "pet_policy", "amenities", "locality", "city", "lat", "lng",
           "thumbnail_key", "published_at"]


def row() -> tuple:
    city = random.choice(list(CITIES))
    locality, lat, lng = random.choice(CITIES[city])
    rent = random.random() < 0.35
    bedrooms = random.choice([1, 2, 2, 2, 3, 3, 4])
    base = {"Mumbai": 1.8, "Bengaluru": 1.2, "Pune": 1.0}[city]
    price = base * bedrooms * (random.randint(9_000, 14_000) if rent else random.randint(3_200_000, 4_800_000))
    return (
        uuid.uuid4(), "rent" if rent else "sale", random.choice(["apartment"] * 6 + ["villa", "independent_house"]),
        f"[perf] {bedrooms} BHK in {locality}", f"Synthetic listing for load testing in {locality}, {city}.",
        int(price) * 100, "INR", bedrooms, max(1, bedrooms - 1), bedrooms * random.randint(380, 520),
        random.choice(["unfurnished", "semi_furnished", "fully_furnished"]), random.choice(["allowed", "not_allowed", "unknown"]),
        random.sample(AMENITIES, k=random.randint(2, 6)), locality, city,
        lat + random.uniform(-0.02, 0.02), lng + random.uniform(-0.02, 0.02), None,
        datetime.now(UTC) - timedelta(days=random.randint(0, 120)),
    )


async def main(count: int, clean: bool, dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        if clean:
            result = await conn.execute("DELETE FROM search_listings WHERE title LIKE '[perf] %'")
            print(f"removed: {result}")
            return
        batch = 5_000
        for start in range(0, count, batch):
            records = [row() for _ in range(min(batch, count - start))]
            await conn.copy_records_to_table("search_listings", records=records, columns=COLUMNS)
            print(f"inserted {start + len(records):,}/{count:,}", flush=True)
        await conn.execute("ANALYZE search_listings")
        print("total rows:", await conn.fetchval("SELECT count(*) FROM search_listings"))
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--dsn", default=DSN)
    args = parser.parse_args()
    asyncio.run(main(args.count, args.clean, args.dsn))

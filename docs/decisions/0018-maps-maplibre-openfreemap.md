# 0018 — Maps: MapLibre GL JS with OpenFreeMap tiles; `near` POIs from a bundled OSM-derived list
- Status: Accepted
- Date: 2026-10-04
- Deciders: Tech lead
- Related: FR-2.3, FR-3.3, T1.12, T3b.7; web/src/components/MapView.tsx, PinMap.tsx; services/search/app/pois.py

## Context
FR-2.3 needs results on a map and "search this area"; agents need to place a map pin (listing fields);
J1 shows a `near: metro` preference that must affect ranking. We want no paid map API and no key to manage.

## Decision
- **Library: MapLibre GL JS** (BSD-3, open source). It's the only new web dependency, and it's lazy-loaded:
  the code is fetched only when someone opens the map view, a listing page with a pin, or the editor.
- **Tiles: OpenFreeMap** (`tiles.openfreemap.org/styles/liberty`) — free OpenStreetMap vector tiles with
  no API key and no usage limits. The OSM attribution stays visible. We don't use
  `tile.openstreetmap.org` directly: its usage policy forbids app traffic.
- **Map-area search:** the search API takes `bbox=minLng,minLat,maxLng,maxLat` (classic and NL), filtering
  on `lat`/`lng` with a btree index (`ix_search_geo`). An invalid box is ignored, not an error.
- **`near` ranking:** `services/search/app/data/pois.csv`, a hand-checked list of ~50 metro/rail stations,
  IT parks, malls, hospitals and airports in the launch cities (approximate, ±200 m, © OpenStreetMap
  contributors, ODbL), held in memory. Score 1.0 within 1.5 km, falling to 0 at 5 km, weight 0.10
  (design.md §4.3). This replaces the `pois` table the design sketched — the list is too small to need one.
- **Accessibility (NFR-6):** the list stays the primary view; the map is an alternative. Pins are focusable
  buttons; the editor also accepts typed coordinates.

## Consequences
- ➕ No key, no bill, nothing to put in Key Vault; the map failing to load never breaks search.
- ➖ OpenFreeMap is a community service with no SLA. If it becomes a problem, self-host its tiles
  (Planetiler output on Blob + Front Door) — only `MAP_STYLE` changes.
- ➖ The POI list must be grown by hand (or by an OSM extract job) before new cities launch.

## Alternatives considered
- **Google Maps / Mapbox** — good, but keyed and billed per load.
- **Leaflet + raster OSM tiles** — simpler, but raster-only and depends on a tile server we may not use.
- **PostGIS** — unnecessary for bounding boxes and a 50-row POI list.

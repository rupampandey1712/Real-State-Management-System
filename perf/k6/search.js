// Classic search load test (FR-2 AC, NFR-8, NFR-9): p95 < 300 ms server-side at 100k listings, 50 RPS.
//   docker run --rm -i --network host -e BASE_URL=http://localhost:8003 grafana/k6 run - < perf/k6/search.js
// BASE_URL = the search service (server-side latency, no gateway rate limits) or the gateway with raised limits.
// Every request is unique (a random budget, a jittered map box) so neither the gateway output cache nor the
// search service's two-level cache (keyed on the parsed filters) can answer it: this measures the database path,
// the worst case. Real traffic repeats queries and is faster.
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL || "http://localhost:8003";

export const options = {
  scenarios: {
    search: { executor: "constant-arrival-rate", rate: Number(__ENV.RPS || 50), timeUnit: "1s", duration: __ENV.DURATION || "60s", preAllocatedVUs: 50, maxVUs: 200 },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{kind:filters}": ["p(95)<300"],
    "http_req_duration{kind:map}": ["p(95)<300"],
    "http_req_duration{kind:near}": ["p(95)<300"],
    "http_req_duration{kind:page2}": ["p(95)<300"],
  },
};

const CITIES = {
  Pune: ["Kharadi", "Baner", "Hinjewadi", "Wakad"],
  Bengaluru: ["Koramangala", "Indiranagar", "Whitefield"],
  Mumbai: ["Andheri West", "Powai", "Thane West"],
};
const BOXES = ["73.70,18.45,74.00,18.65", "77.55,12.90,77.80,13.05", "72.80,19.00,73.00,19.25"];
const pick = (a) => a[Math.floor(Math.random() * a.length)];

function query() {
  const city = pick(Object.keys(CITIES));
  const roll = Math.random();
  // a unique upper budget per request defeats every cache layer (rent ≤ ₹2 L/month, sale ≤ ₹5 Cr)
  const p = { city, limit: 20, price_max: 2_000_000 + Math.floor(Math.random() * 48_000_000) };
  if (roll < 0.55) {
    Object.assign(p, { listing_type: pick(["sale", "rent"]), bedrooms_min: pick([1, 2, 3]), sort: pick(["newest", "price_asc", "price_desc", "relevance"]) });
    if (Math.random() < 0.5) p.locality = pick(CITIES[city]);
    if (Math.random() < 0.3) p.amenities = pick(["gym", "lift", "swimming_pool"]);
    return { p, kind: "filters" };
  }
  if (roll < 0.75) {
    const [w, s, e, n] = pick(BOXES).split(",").map(Number);
    const j = () => (Math.random() - 0.5) * 0.05;
    return { p: { ...p, bbox: [w + j(), s + j(), e + j(), n + j()].map((v) => v.toFixed(5)).join(",") }, kind: "map" };
  }
  if (roll < 0.9) return { p: { ...p, near: pick(["metro", "it_park"]), sort: "relevance" }, kind: "near" };
  return { p: { ...p, cursor: "MjA=" }, kind: "page2" }; // offset 20
}

export default function () {
  const { p, kind } = query();
  const qs = Object.entries(p).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  const res = http.get(`${BASE}/api/v1/search?${qs}`, { tags: { kind, name: `search:${kind}` } });
  check(res, { "status 200": (r) => r.status === 200 });
}

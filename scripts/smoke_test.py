"""End-to-end smoke test against the running docker compose stack, through the gateway like the browser.

    python scripts/smoke_test.py            (stack must be up: docker compose up -d)

Covers: health, seeding → outbox → Service Bus → search index, classic + NL search, OTP sign-in,
refresh-cookie rotation, roles at the edge, create/publish listing (with an idempotent retry), PDF
upload → AI ingestion → status event back, Q&A streaming, AI description, enquiry → email in Mailpit,
favourites, saved searches, logout revocation, and the web app. Exits 1 on the first failure.
"""

import io
import json
import sys
import time
import uuid

import httpx

GATEWAY = "http://localhost:8080"
MAILPIT = "http://localhost:8025"
WEB = "http://localhost:3000"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    ok = bool(ok)
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}", flush=True)
    if not ok:
        summary()
        sys.exit(1)


def wait_for(name: str, probe, timeout_s: float = 60, interval_s: float = 2):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            last = probe()
            if last:
                return last
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(interval_s)
    check(name, False, f"timed out after {timeout_s:.0f}s (last: {last!r})"[:300])


def summary() -> None:
    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")


def sign_in(client: httpx.Client, email: str) -> str:
    code = client.post("/api/v1/auth/otp/request", json={"email": email}).json()["dev_code"]
    response = client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    response.raise_for_status()
    return response.json()["access_token"]


def minimal_pdf(text: str) -> bytes:
    """A valid one-page PDF with extractable text (no dependencies)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def main() -> None:
    gw = httpx.Client(base_url=GATEWAY, timeout=30)

    # ── platform health ──────────────────────────────────────────────────────────
    deep = wait_for("gateway sees all services healthy",
                    lambda: (r := gw.get("/health/deep").json())["status"] == "ok" and r, timeout_s=120)
    check("gateway /health/deep", True, ", ".join(f"{k}:{v[0]['active']}" for k, v in deep["clusters"].items()))
    check("internal routes blocked at the edge", gw.get("/internal/listings/x/facts").status_code == 404)

    # ── seed → outbox → Service Bus → search projection ──────────────────────────
    seeded = httpx.post("http://localhost:8002/internal/dev/seed?count=30", timeout=60).json()["created"]
    check("seed listings (events staged in outbox)", seeded == 30, f"{seeded} created")
    found = wait_for("search index filled via events",
                     lambda: len(gw.get("/api/v1/search", params={"limit": 50, "nocache": uuid.uuid4().hex}).json()["items"]) >= 20,
                     timeout_s=90)
    check("outbox → Service Bus → search projection", bool(found))

    classic = gw.get("/api/v1/search", params={"city": "Pune", "bedrooms_min": 2})
    check("classic search", classic.status_code == 200 and all(i["city"] == "Pune" for i in classic.json()["items"]),
          f"{len(classic.json()['items'])} Pune results")
    nl = gw.post("/api/v1/search/nl", json={"query": "2bhk under 80 lakh in pune near metro"}).json()
    check("NL search (AI parse + hybrid ranking)",
          nl["interpreted_filters"]["city"] == "Pune" and nl["interpreted_filters"]["bedrooms_min"] == 2,
          f"mode={nl['meta']['mode']}, {len(nl['items'])} results")

    amenity = gw.post("/api/v1/search/nl", json={"query": "2 bhk with gym and lift"})
    check("NL search with amenity filters", amenity.status_code == 200
          and set(amenity.json()["interpreted_filters"]["amenities"]) == {"gym", "lift"}, f"{len(amenity.json().get('items', []))} results")
    classic_amenity = gw.get("/api/v1/search", params=[("amenities", "gym"), ("amenities", "lift")])
    check("classic search with amenity filters", classic_amenity.status_code == 200
          and all({"gym", "lift"} <= set(i.get("amenities", ["gym", "lift"])) for i in classic_amenity.json()["items"]))

    # ── auth ──────────────────────────────────────────────────────────────────────
    buyer = httpx.Client(base_url=GATEWAY, timeout=30)
    buyer_token = sign_in(buyer, f"buyer-{uuid.uuid4().hex[:8]}@example.com")
    check("OTP sign-in issues RS256 token + refresh cookie",
          buyer_token.count(".") == 2 and "estate_refresh" in buyer.cookies)
    buyer.headers["Authorization"] = f"Bearer {buyer_token}"
    check("GET /me with token", buyer.get("/api/v1/me").json()["role"] == "buyer")
    check("buyer blocked from agent routes at the edge", buyer.get("/api/v1/agent/listings").status_code == 403)
    old_cookie = buyer.cookies["estate_refresh"]
    refreshed = buyer.post("/api/v1/auth/refresh", headers={"Authorization": ""})
    check("refresh rotates the cookie", refreshed.status_code == 200 and buyer.cookies["estate_refresh"] != old_cookie)
    reuse = httpx.post(f"{GATEWAY}/api/v1/auth/refresh", cookies={"estate_refresh": old_cookie})
    check("reusing a rotated refresh token is rejected", reuse.status_code == 401)
    buyer.headers["Authorization"] = f"Bearer {refreshed.json()['access_token']}"

    # ── agent: create (idempotent) → publish → searchable ──────────────────────────
    agent = httpx.Client(base_url=GATEWAY, timeout=60)
    agent.headers["Authorization"] = f"Bearer {sign_in(agent, 'agent@example.com')}"
    payload = {
        "listing_type": "sale", "property_type": "apartment", "title": "Smoke test 2 BHK in Kharadi",
        "description": "Test listing created by the smoke test.", "price_inr": 7_500_000, "maintenance_inr": 3500,
        "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 900, "pet_policy": "allowed", "amenities": ["gym", "lift"],
        "address_line": "Smoke Tower", "locality": "Kharadi", "city": "Pune",
    }
    key = uuid.uuid4().hex
    first = agent.post("/api/v1/listings", json=payload, headers={"Idempotency-Key": key})
    second = agent.post("/api/v1/listings", json=payload, headers={"Idempotency-Key": key})
    check("create listing is idempotent", first.status_code == 201 and second.json()["id"] == first.json()["id"]
          and second.headers.get("Idempotent-Replayed") == "true")
    listing_id = first.json()["id"]
    check("publish listing", agent.post(f"/api/v1/listings/{listing_id}/publish").json()["status"] == "published")
    wait_for("published listing appears in search",
             lambda: any(i["id"] == listing_id for i in gw.get("/api/v1/search", params={
                 "locality": "Kharadi", "limit": 50, "nocache": uuid.uuid4().hex}).json()["items"]), timeout_s=60)
    check("publish → event → searchable", True)

    # ── document → AI ingestion → status event back ────────────────────────────────
    pdf = minimal_pdf("Society rules: pets are allowed. Dogs must be leashed in common areas.")
    doc = agent.post(f"/api/v1/listings/{listing_id}/documents", files={"file": ("rules.pdf", pdf, "application/pdf")},
                     data={"kind": "society_rules"})
    check("upload PDF", doc.status_code == 201, doc.json().get("status", ""))
    ready = wait_for("document processed by AI service",
                     lambda: (d := agent.get(f"/api/v1/listings/{listing_id}/documents").json()) and d[0]["status"] in ("ready", "failed") and d[0],
                     timeout_s=90)
    check("listing → ai (ingest) → listing (status)", ready["status"] == "ready", ready["status"] + (f": {ready['error']}" if ready["error"] else ""))

    # ── AI features ────────────────────────────────────────────────────────────────
    with buyer.stream("POST", f"/api/v1/listings/{listing_id}/qa", json={"question": "What is the monthly maintenance?"}) as r:
        body = "".join(r.iter_text())
    events = [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]
    answer = "".join(e.get("text", "") for e in events if "text" in e)
    check("Q&A streams a cited answer (SSE through gateway)", "3,500" in answer and "[S" in answer, answer[:90])
    describe = agent.post("/api/v1/ai/describe", json={"listing_id": listing_id, "tone": "warm", "length": "short"})
    check("AI description draft", describe.status_code == 200 and describe.json()["title"], describe.json().get("title", "")[:60])

    # ── engagement ─────────────────────────────────────────────────────────────────
    marker = uuid.uuid4().hex[:8]
    enquiry = buyer.post(f"/api/v1/listings/{listing_id}/enquiries", headers={"Idempotency-Key": uuid.uuid4().hex},
                         json={"name": "Smoke Buyer", "email": "buyer@example.com", "message": f"Is it available? {marker}"})
    check("send enquiry", enquiry.status_code == 201)
    wait_for("agent email delivered (engagement → Service Bus → notification → Mailpit)",
             lambda: any("Smoke test 2 BHK" in m["Subject"] for m in httpx.get(f"{MAILPIT}/api/v1/messages").json()["messages"]),
             timeout_s=60)
    check("enquiry → email in Mailpit", True)
    check("add favourite", buyer.put(f"/api/v1/me/favourites/{listing_id}").status_code == 204)
    check("list favourites", any(f["listingId"] == listing_id for f in buyer.get("/api/v1/me/favourites").json()))
    saved = buyer.post("/api/v1/me/saved-searches", json={"name": "Kharadi 2BHK", "raw_query": "2bhk kharadi", "filters": {}})
    check("save a search", saved.status_code == 201)

    # ── logout revokes the live access token ───────────────────────────────────────
    token = buyer.headers["Authorization"]
    check("logout", buyer.post("/api/v1/auth/logout").status_code == 204)
    check("revoked token rejected at the edge", httpx.get(f"{GATEWAY}/api/v1/me", headers={"Authorization": token}).status_code == 401)

    # ── web app ────────────────────────────────────────────────────────────────────
    page = httpx.get(WEB, timeout=10)
    check("web app served", page.status_code == 200 and '<div id="root">' in page.text)
    check("web → gateway proxy", httpx.get(f"{WEB}/api/v1/search?limit=1", timeout=10).status_code == 200)
    summary()


if __name__ == "__main__":
    main()

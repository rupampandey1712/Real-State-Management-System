# Requirements — EstateAI

> Status: Draft v0.2 · Owner: Product · Last updated: 2026-09-27
> Related: [design.md](design.md) · [plan.md](plan.md) · [glossary.md](glossary.md)

---

## 1. Vision & problem statement

**Vision:** Make finding and listing a home as easy as describing it to a knowledgeable friend.

**Problem**
- **Buyers/renters** think in natural language ("2BHK near a metro, quiet, under 80 lakh, okay with pets")
  but portals force rigid filters. They miss good matches and waste time on bad ones.
- **Agents** spend 20–40 minutes writing each listing description and repeatedly answer the same
  questions (parking? maintenance? pets?) over phone/WhatsApp.
- **Trust:** AI chatbots that "make things up" are dangerous in real estate, where wrong facts
  (area, legal status, fees) have financial consequences.

**Our answer:** GenAI features that are **grounded in listing data**, show their reasoning
(interpreted filters, citations), and always degrade to classic behaviour.

## 2. Goals & non-goals

| Goals (MVP) | Non-goals (MVP) |
|---|---|
| NL search that beats filters on relevance | Transactions, payments, escrow |
| Agents publish listings in < 10 minutes | Automated price valuation (AVM) |
| Buyers get instant, cited answers per listing | Legal/title verification |
| Zero fabricated facts in AI output | Native iOS/Android apps |
| AI cost within budget (NFR-3) | Multi-language queries (Phase 5) |
| | Agent CRM / lead management |

## 3. Personas

### P1 — Priya, first-time buyer (primary)
- 29, software engineer in Pune, budget ₹70–90 lakh, commutes by metro.
- Browses on mobile in the evening; hates calling agents for basic facts.
- **Needs:** describe what she wants in her own words; trust the answers.

### P2 — Rahul, renter relocating
- 34, moving to Bengaluru for a job; searching remotely; has a dog.
- **Needs:** filter by pet-friendliness, commute, furnishing; quick answers without site visits.

### P3 — Meera, independent agent (primary)
- Manages 30–60 active listings; lists from her phone after site visits.
- **Needs:** fast listing creation, good descriptions, fewer repetitive enquiries.

### P4 — Admin / Trust & Safety
- **Needs:** moderate listings, see AI quality/cost, investigate complaints.

## 4. User journeys (happy paths)

**J1 — NL search to enquiry (Priya)**
1. Types "2BHK under 80 lakh near a metro in Pune, east facing" on home page.
2. Sees results with chips: `Pune` `2 BHK` `≤ ₹80 L` `Sale` `near: metro` `facing: east`.
3. Removes the `facing: east` chip → results refresh instantly (no LLM call).
4. Opens a listing, asks "What's the monthly maintenance?" → gets answer with `[S2]` citation.
5. Asks "Is the society okay with pets?" → "I don't have that information" + **Ask the agent** button.
6. Taps **Ask the agent** → enquiry form (name, phone, message pre-filled with the question).

**J2 — Agent creates a listing (Meera)**
1. Opens "New listing", fills structured fields (≈ 20 fields, most are pickers), uploads 8 photos.
2. Clicks **Generate description** → chooses tone "Warm", length "Medium".
3. Gets title + description + 5 highlights in < 8 s; edits one sentence; publishes.
4. Uploads the society rules PDF → status "Processing…" → "Ready for Q&A" within 2 minutes.

## 5. Functional requirements

Priority uses MoSCoW: **M**ust, **S**hould, **C**ould. Acceptance criteria (AC) in Given/When/Then.

### FR-1 Listings management
| ID | Story | Pri |
|---|---|---|
| FR-1.1 | As an agent, I can create, edit, publish, unpublish, and archive a listing. | M |
| FR-1.2 | As an agent, I can upload up to 30 images (JPEG/PNG/WebP/HEIC, ≤ 15 MB each) and reorder them. | M |
| FR-1.3 | As an agent, I can upload up to 10 documents (PDF, ≤ 20 MB each) for Q&A grounding. | M |
| FR-1.4 | As an agent, I can enter the RERA registration number for projects that require it. | M |
| FR-1.5 | As an agent, I can duplicate an existing listing as a starting point. | C |

**Listing fields:** title, description, listing type (sale/rent), property type
(apartment/independent house/villa/plot/commercial), price (or monthly rent), deposit (rent),
maintenance/month, bedrooms (BHK), bathrooms, balconies, carpet area, built-up area,
floor / total floors, facing, furnishing (unfurnished/semi/full), parking (covered/open counts),
age of property / possession date, amenities (multi-select from controlled list), pet policy
(allowed/not allowed/unknown), address, locality, city, pincode, geo-coordinates (map pin), RERA ID.

**AC**
- Given required fields are missing, when the agent publishes, then publishing is blocked and each
  missing field is highlighted with a message.
- Given carpet area > built-up area, when saving, then a validation error is shown.
- Given an image is uploaded, then thumbnails (400 px) and display (1600 px) WebP variants are
  generated within 30 s and EXIF location data is stripped.
- Given a listing is unpublished, then it disappears from search within 60 s and its page returns 404 to non-owners.

### FR-2 Classic search & browse
| ID | Story | Pri |
|---|---|---|
| FR-2.1 | As a buyer, I can filter by city, locality, listing type, price range, BHK, property type, furnishing, amenities, pet policy. | M |
| FR-2.2 | As a buyer, I can sort by relevance, price (asc/desc), newest. | M |
| FR-2.3 | As a buyer, I can see results on a map and search within the visible map area. | S |
| FR-2.4 | As a buyer, the filter state is reflected in the URL so I can share/bookmark it. | M |

**AC**
- p95 latency < 300 ms at 100k published listings (server-side, excl. network).
- Page size 20, cursor pagination; results stable across pages.

### FR-3 AI natural-language search
| ID | Story | Pri |
|---|---|---|
| FR-3.1 | As a buyer, I can type a free-text query in English (incl. Indian units: lakh, crore, BHK, sq ft). | M |
| FR-3.2 | I see the interpreted filters as removable/editable chips. | M |
| FR-3.3 | Results are ranked by filter match + semantic relevance to soft preferences ("quiet", "lots of light"). | M |
| FR-3.4 | If my query is not a property search ("what is the weather"), I get a friendly hint, not an error. | S |
| FR-3.5 | I can save an NL search and re-run it later. | S |

**AC**
- Given "2bhk under 80L in pune", then filters = `{city: Pune, bedrooms: 2, price_max: 8000000 INR, listing_type: sale}`.
- Given "1 BHK for rent in Koramangala below 25k", then `listing_type = rent`, `price_max = 25000` (monthly), `locality = Koramangala`, `city = Bengaluru`.
- Given the LLM times out (> 1.5 s), then results are still returned using keyword + vector search, with a subtle "showing broad matches" note.
- Filter-extraction field accuracy ≥ 90% on `evals/search` (150 cases); p95 end-to-end < 2.5 s.
- Editing a chip re-runs classic search without an LLM call.

### FR-4 AI listing description generator
| ID | Story | Pri |
|---|---|---|
| FR-4.1 | As an agent, I can generate a title, description, and 3–6 highlights from the listing's fields. | M |
| FR-4.2 | I can choose tone (Professional / Warm / Luxury) and length (Short ~60 words / Medium ~120 / Long ~200). | M |
| FR-4.3 | I can regenerate, edit freely, and must explicitly accept before it is saved. | M |
| FR-4.4 | I can "improve my text" — rewrite my own draft description in a chosen tone. | C |

**AC**
- Output contains **no facts absent from the input** (0 violations on `evals/describe`, 50 cases).
- Numbers in output (BHK, area, floor, price) exactly match input values.
- No fair-housing violations (see `docs/ai/guardrails.md` §4).
- p95 generation time < 8 s.

### FR-5 AI listing Q&A assistant
| ID | Story | Pri |
|---|---|---|
| FR-5.1 | As a buyer, I can ask questions in a chat panel on a listing page. | M |
| FR-5.2 | Answers use only that listing's fields + its uploaded documents, with citations I can click. | M |
| FR-5.3 | If the answer isn't available, the assistant says so and offers "Ask the agent". | M |
| FR-5.4 | Suggested starter questions are shown (e.g. "What's the maintenance?", "Is parking included?"). | S |
| FR-5.5 | Answers stream token-by-token. | S |
| FR-5.6 | I can rate an answer 👍/👎 with optional comment. | M |

**AC**
- ≥ 95% groundedness on `evals/qa` (100 cases); ≥ 95% correct "unknown" on unanswerable cases.
- 0 successful prompt injections / fabrications on `evals/qa/redteam` (30 cases).
- First token p95 < 2 s; full answer p95 < 8 s.
- Refuses legal/financial advice ("Is this a good investment?") and redirects politely.

### FR-6 Accounts & personalisation
| ID | Story | Pri |
|---|---|---|
| FR-6.1 | Sign in with email magic link or Google; roles buyer (default), agent (verified), admin. | M |
| FR-6.2 | Buyers can favourite listings and save searches. | S |
| FR-6.3 | Buyers can send an enquiry to the agent (contact shared only with that agent). | M |
| FR-6.4 | Users can delete their account and data (DPDP compliance). | M |

### FR-7 Admin & trust
| ID | Story | Pri |
|---|---|---|
| FR-7.1 | Admin can unpublish/restore listings and suspend agents, with reason logged. | M |
| FR-7.2 | Admin AI dashboard: requests, tokens, cost, latency, error rate, 👍/👎 ratio per feature per day. | M |
| FR-7.3 | Admin can view negative-feedback AI interactions (PII-redacted) and export them as eval cases. | S |
| FR-7.4 | Admin can toggle AI feature flags at runtime. | S |

## 6. Non-functional requirements

| ID | Category | Requirement | Measure |
|---|---|---|---|
| NFR-1 | Availability | 99.5% monthly for web + API | Uptime monitor |
| NFR-2 | Resilience | AI outage must not break search/listing pages | Chaos test: block LLM egress |
| NFR-3 | Cost | Avg LLM cost < $0.01 per NL search, < $0.03 per Q&A turn, < $0.05 per description | `ai_requests` cost report |
| NFR-4 | Security | OWASP ASVS L1; RBAC on every endpoint; secrets server-side only | Security review checklist |
| NFR-5 | Privacy | No buyer PII to LLM/embedding providers; logs PII-redacted; DPDP Act 2023 compliant | Log audit, test |
| NFR-6 | Accessibility | WCAG 2.1 AA; keyboard-usable chat and map alternatives | axe + manual audit |
| NFR-7 | Observability | Structured logs, traces, per-feature AI metrics, alerts | Dashboards exist |
| NFR-8 | Performance | LCP < 2.5 s on 4G for listing page; API p95 < 300 ms (non-AI) | Lighthouse, k6 |
| NFR-9 | Scalability | 100k listings, 1M doc chunks, 50 RPS search on a single DB node | Load test |
| NFR-10 | Data retention | AI logs 30 days; enquiries 2 years; deleted accounts purged within 30 days | Scheduled jobs |
| NFR-11 | Browser support | Last 2 versions of Chrome, Safari, Firefox, Edge; mobile-first | Playwright matrix |

## 7. Compliance & legal constraints
- **RERA (India):** listings for registered projects must display the RERA registration number.
- **DPDP Act 2023:** consent for data collection, purpose limitation, right to erasure, breach notification.
- **Fair housing / non-discrimination:** no listing or AI text may express preference or exclusion
  based on religion, caste, community, gender, marital status, or diet.
- **AI transparency:** AI-generated descriptions are labelled "AI-assisted" internally; Q&A panel
  shows "AI answers can be incomplete — verify with the agent."

## 8. Assumptions & constraints
- Launch cities: Pune, Bengaluru, Mumbai. Currency INR. English UI.
- Small team (2–3 engineers + AI coding agents), 8-week MVP.
- Google Gemini (paid tier) is the LLM and embedding provider (ADR-0013); Azure Central India region for everything else.
- Seed data will be synthetic/licensed — no scraping of other portals.

## 9. Success metrics (measured 60 days post-launch)
| Metric | Target |
|---|---|
| Search → listing-view CTR (NL vs classic) | +20% |
| Share of searches using NL box | ≥ 40% |
| Median agent time-to-publish | ≤ 10 min (−50%) |
| Descriptions accepted with ≤ 20% edits | ≥ 60% |
| Q&A 👍 ratio | ≥ 80% |
| Q&A questions answered without agent contact | ≥ 50% |
| Reported AI factual errors | < 1 per 1,000 answers |

## 10. Open questions
| # | Question | Owner | Needed by |
|---|---|---|---|
| Q1 | Confirm launch cities and INR-only | Product | Phase 1 |
| Q2 | Hindi/regional queries in MVP or Phase 5? | Product | Phase 3 |
| Q3 | Embedding provider choice (ADR-0003) | Eng | Phase 2 |
| Q4 | Agent verification process (manual KYC?) | Ops | Phase 1 |
| Q5 | Should enquiries go by email, WhatsApp, or in-app only? | Product | Phase 4 |

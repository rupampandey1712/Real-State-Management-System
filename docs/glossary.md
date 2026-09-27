# Glossary

Domain and project terms. Use these names in code, UI copy, and docs.

## Real estate (India)
| Term | Meaning | In code |
|---|---|---|
| **BHK** | Bedroom-Hall-Kitchen; "2 BHK" = 2 bedrooms + hall + kitchen | `bedrooms` |
| **1 RK** | 1 Room + Kitchen (studio) | `bedrooms = 0` |
| **Lakh (L, lac)** | 1,00,000 INR (100 thousand) | `money.LAKH = 100_000` |
| **Crore (Cr)** | 1,00,00,000 INR (10 million) | `money.CRORE = 10_000_000` |
| **Carpet area** | Usable floor area inside walls (RERA-defined) | `carpet_area_sqft` |
| **Built-up area** | Carpet area + wall thickness + balconies | `builtup_area_sqft` |
| **Super built-up area** | Built-up + share of common areas (not stored — often misleading) | — |
| **RERA** | Real Estate (Regulation and Development) Act, 2016; projects register with state RERA authority | `rera_id` |
| **Possession** | When the buyer can take the property ("ready to move" or a future date) | `possession_date` |
| **Resale** | Previously owned property (vs new from builder) | `attributes.resale` |
| **Society** | Housing society / residents' association managing the building | — |
| **Maintenance** | Monthly charge paid to the society | `maintenance_minor` |
| **Deposit** | Refundable security deposit for rentals (often 2–10 months' rent) | `deposit_minor` |
| **Facing** | Direction the main door/balcony faces (valued for vastu/light) | `facing` |
| **Semi-furnished** | Typically wardrobes, fans, lights, kitchen fittings; no appliances/furniture | `furnishing` |
| **Locality** | Neighbourhood within a city (e.g. Kharadi, Koramangala) | `locality` |
| **Pincode** | 6-digit Indian postal code | `pincode` |

## Product
| Term | Meaning |
|---|---|
| **Listing** | A property offered for sale or rent by an agent |
| **Agent** | Verified user who creates listings (may be owner, broker, or builder rep) |
| **Enquiry** | A buyer's contact request to the agent about a listing |
| **Interpreted filters / chips** | The structured filters extracted from an NL query, shown as editable chips |
| **Soft preferences** | Non-filterable wishes ("quiet", "good light") used only for semantic ranking |
| **Assumptions** | User-facing notes about what the AI guessed |
| **Fact sheet** | Canonical, citable list of a listing's structured facts (S1..Sn) used by AI features |
| **Fallback mode** | Search results produced without the LLM (FTS + vectors) |

## AI / engineering
| Term | Meaning |
|---|---|
| **LLM gateway** | `services/ai/app/llm/` — the only code that calls the LLM provider (ADR-0004, 0013) |
| **API gateway** | `services/gateway` — the single public HTTP entry point for the web app (architecture.md §2) |
| **Structured output** | Gemini returns JSON matching a supplied schema (`response_json_schema`); we validate it with Pydantic |
| **Prompt version** | Immutable prompt file `<id>.v<N>.md`; active version chosen via config |
| **Prompt caching** | Reusing the processed system prompt across calls to cut cost and latency |
| **RAG** | Retrieval-Augmented Generation — retrieve relevant context, then generate an answer grounded in it |
| **Chunk** | A 500–800-token piece of a document, embedded for retrieval |
| **Embedding** | Numeric vector representing text meaning; compared with cosine similarity |
| **Hybrid search** | Combining hard SQL filters, full-text, and vector similarity in one ranking |
| **Grounded** | Every factual claim is supported by the provided context |
| **Citation** | `[S#]` (fact sheet) or `[D#]` (document chunk) marker in a Q&A answer |
| **Eval / eval suite** | Versioned dataset + scorers measuring AI quality; gates releases |
| **Gate** | Minimum eval score required to enable/ship an AI change |
| **LLM-as-judge** | Using a strong model with a rubric to score outputs |
| **Red-team set** | Adversarial eval cases (injection, jailbreaks, abuse) |
| **Prompt injection** | Untrusted text trying to override the model's instructions |
| **Feature flag** | Runtime switch to enable/disable a feature without deploying |
| **nDCG@10** | Ranking quality metric for the top 10 results |

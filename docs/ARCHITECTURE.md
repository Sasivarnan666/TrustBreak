# Architecture

## Overview

```
 Browser (React SPA, :5173)
        │  fetch("/api/...")            Vite dev server proxies /api
        ▼
 FastAPI app (:8000)
   routers/incidents.py   HTTP only: parse, call repository, wrap in envelope
   schemas.py             Pydantic: request validation + response shapes
   repository.py          SQL (stdlib sqlite3), row <-> model mapping
   services/analysis.py   PLACEHOLDER analysis (replaceable seam)
   services/message_analysis/  message -> validated structured JSON (AI or labelled demo mock)
   services/behaviour/    synthetic profile + deterministic anomaly signals (no scoring)
   services/attachment_analysis/  safe static file inspection (no scoring)
   services/risk_correlation/  combines the three analyzers' outputs -> explainable risk assessment
   errors.py + main.py    one JSON envelope for success and every failure
        │
        ▼
 SQLite file  data/trustbreak.db   (one `incidents` table)
```

Frontend and backend share nothing except the REST contract below.

## Backend modules (`backend/app/`)

| Module | Responsibility | Does NOT |
|---|---|---|
| `main.py` | App factory, lifespan (create DB, seed demo), CORS, error handlers, `/api/health` | contain business logic |
| `routers/incidents.py` | The incident endpoints (CRUD plus on-demand message, behaviour, attachment and risk analysis) | touch SQL directly |
| `schemas.py` | Validation rules and response models | know about the database |
| `repository.py` | Create / get / list / count incidents | validate input or decide risk |
| `services/analysis.py` | `analyze_incident(payload) -> Analysis` | persist anything |
| `database.py` | Connections, schema, `get_db` dependency | |
| `seed.py` | Synthetic demo incident | |
| `config.py` | Env-var settings, read at call time | |
| `errors.py` | `AppError`, `error_body()` | |

### Message analysis service (`services/message_analysis/`)

```
message ──> analyze_message() ──┬─ AI mode:   prompt.py -> ai_provider.py (Anthropic, stdlib urllib)
 (untrusted)                    │                 reply -> parse_model_reply -> validate_extraction (strict)
                                └─ mock mode: mock_extractor.py (regex rules, NOT AI) -> same validate_extraction
                                          ▼
                              MessageAnalysis { mode, model, extraction, notes, fallback_reason, is_final_decision=false }
```

| Module | Responsibility |
|---|---|
| `schema.py` | Dataclasses + `validate_extraction` (exact keys, enums, types, ranges). Stdlib only. |
| `prompt.py` | System prompt (message = untrusted data) and per-request random-delimiter wrapping |
| `ai_provider.py` | One HTTPS call to the Anthropic Messages API; raises `ProviderError`; never echoes secrets |
| `mock_extractor.py` | Deterministic demo rules; output also passes `validate_extraction` |
| `service.py` | Mode selection (`auto`/`ai`/`mock`), fallback policy, `ExtractionError` |

Rules: nothing outside this package imports the provider or the prompt; the router calls only `analyze_message`; a future risk engine reads `MessageAnalysis.extraction` and has no LLM dependency. The core is stdlib-only (testable without FastAPI); the pydantic models in `schemas.py` (`MessageAnalysisOut`…) only shape the HTTP response. `POST /api/incidents/{id}/analyze-message` is computed on demand and not stored.

### Behaviour service (`services/behaviour/`)

```
Incident (sender, channel, amount, beneficiary)
   -> get_profile_for_sender()  -> BehaviourProfile (synthetic registry)
   -> analyze_behaviour()       -> { *_anomaly flags, checks, anomalies[], notes, is_final_decision=false }
```

| Module | Responsibility |
|---|---|
| `profile.py` | `BehaviourProfile` dataclass, name normalisation, synthetic demo registry (CEO-001, CFO-001) |
| `analyzer.py` | Pure, deterministic rules (amount ratio to typical max, known beneficiary, normal channel); never raises on missing data |
| `__init__.py` | `analyze_incident_behaviour(sender_name, channel, amount, beneficiary)` |

Rules: independent of message analysis and of `analyze_incident`; stdlib only; not connected to any score. The risk correlation engine that consumes it is described below. `POST /api/incidents/{id}/analyze-behaviour` is computed on demand and not stored. Frequency analysis would need per-sender request history and is deliberately deferred.

### Attachment analysis service (`services/attachment_analysis/`)

```
Uploaded file (multipart, in memory)
   -> detect_type()        (signature bytes, not the name)
   -> ZipFile.infolist()   (central directory only; no member is read, extracted or written)
   -> analyze_attachment() -> { file_type, archive, file_count, entries[], contains_executable,
                                suspicious, findings[], notes, is_final_decision=false }
```

| Module | Responsibility |
|---|---|
| `config.py` | Extension denylists/labels, document keywords, expected-type map, limits (upload size via `TRUSTBREAK_MAX_UPLOAD_BYTES`, default 10 MiB) |
| `analyzer.py` | Pure, deterministic checks; raises `AttachmentError` only for unusable input (empty, too large, bad name) - malformed content becomes a finding |
| `__init__.py` | `analyze_attachment`, `AttachmentError`, `detect_type` |

Rules: no execution, extraction, file writes, shell calls or network access (enforced by tests); independent of message/behaviour analysis and of any score. Because the incident stores attachment metadata only, `POST /api/incidents/{id}/analyze-attachment` takes the file as multipart field `file`, analyzes it during the request and discards it. Its output is consumed by the risk correlation engine (below).

### Risk correlation engine (`services/risk_correlation/`)

```
Message Analysis ─────┐
Behaviour Analysis ───┼──>  Risk Correlation Engine  ──>  Explainable Risk Assessment
Attachment Analysis ──┘     (deterministic rules)          score · level · action · signals[]
```

```
Incident ──┬─ analyze_message()           ─┐
           ├─ analyze_incident_behaviour() ─┼─> correlate_risk(message, behaviour, attachment, incident)
           └─ analyze_attachment(file)?   ─┘        -> RiskCorrelationResult
```

| Module | Responsibility |
|---|---|
| `rules.py` | The scoring table in one place: categories, prototype point weights, level thresholds, action mapping, finding-type and intent mappings, wording. Stdlib only. |
| `engine.py` | `correlate_risk(...)`: pure and stdlib-only, no I/O, never raises on missing or odd input, imports none of the analyzers. At most one signal per category; adds points; caps the displayed score at 100; maps score -> level -> action; sets `trust_break_detected`. |
| `service.py` | `assess_incident_risk(incident, attachment_file=None)`: the **only** module that imports the analyzers. A message-analysis failure becomes "unavailable" evidence, not a failed request. |

Rules: the correlation layer sits **above** the analyzers. They stay independently usable and import nothing from each other or from this package (enforced by an AST test); no LLM is consulted for the score; the engine only recommends and never blocks or executes a payment. Scores are heuristic risk points, not probabilities. `POST /api/incidents/{id}/analyze-risk` takes an optional multipart `file` (attachment evidence needs the bytes, which are not stored), is computed on demand and not stored. See PROJECT_STATE for the weight table, thresholds and limitations.

### The analysis seam

`analyze_incident` is the single place future detection plugs in. Today it is still a placeholder (the risk correlation engine runs on demand beside it and is not stored; persisting it is the next planned step): it returns `risk_status = "needs_review"`, a fixed recommended action, and evidence items that are the submitted facts (`source = "submitted"`). The result is computed once at creation and stored with the incident. Replacing it with real analysis should not change the router, the schemas' envelope, or the frontend's data flow.

## Data model

Single table `incidents` (flat columns; the API nests them):

| Group | Columns |
|---|---|
| Identity | `id`, `created_at` (UTC ISO-8601 `Z`), `title` |
| Sender | `sender_name`, `sender_role`, `sender_known`, `sender_contact` |
| Channel | `channel` (WhatsApp, Email, SMS, Phone call, Other) |
| Payment | `amount` (integer rupees), `currency` (`INR`), `beneficiary_name`, `beneficiary_is_new` |
| Message | `message` |
| Attachment (metadata only) | `attachment_name`, `attachment_size_bytes`, `attachment_content_type` |
| Analysis | `analysis_mode`, `risk_status`, `analysis_summary`, `recommended_action`, `evidence_json` |

Decisions: amounts are whole rupees (no float money); `reference` (`TB-0001`) is derived from `id`, not stored; no file contents or bank account numbers are ever stored.

## REST contract

Envelope (every endpoint, including errors):

```
success: { "success": true,  "data": <object|array>, "meta"?: { total, count, limit, offset } }
failure: { "success": false, "error": { "code", "message", "details": [{ "field", "message" }] } }
```

`POST /api/incidents` body (flat): `sender_name`, `sender_role`, `sender_known`, `sender_contact?`, `channel`, `amount`, `beneficiary_name`, `beneficiary_is_new`, `message`, `attachment_name?`, `attachment_size_bytes?`, `attachment_content_type?`. Unknown fields are rejected.

Incident detail (`GET /api/incidents/{id}`) returns nested `sender`, `payment`, `attachment` (nullable) and `analysis { mode, risk_status, summary, recommended_action, evidence[] }`. List rows are flat summaries.

## Frontend (`frontend/src/`)

| Path | Role |
|---|---|
| `api/client.js` | `fetch` wrapper; throws `ApiError` (`code`, `status`, `details`) |
| `hooks/useAsync.js` | Load/error/reload with abort on unmount |
| `lib/` | `format.js` (₹ en-IN, dates, bytes), `risk.js` (status display), `validation.js` (form rules mirroring the backend) |
| `components/` | `Layout`, `ui` (Card, Button, PageHeader…), `StatusBadge`, `States` (loading/error/empty) |
| `pages/` | `Dashboard`, `IncidentList`, `IncidentDetail`, `CreateIncident` |

Pages that display data are split into a fetching component and a pure `*View` component, so rendering can be tested without a server.

## Deliberate non-goals (this phase)

No authentication, no risk scoring or fraud verdict (AI only extracts message fields; behaviour analysis only emits signals from synthetic profiles), no stored behavioural history, no stored files (attachments are analyzed in memory and discarded), no external integrations (banking, WhatsApp), no payment processing, no migrations tooling.

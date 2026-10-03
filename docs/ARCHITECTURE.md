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
| `routers/incidents.py` | The three incident endpoints | touch SQL directly |
| `schemas.py` | Validation rules and response models | know about the database |
| `repository.py` | Create / get / list / count incidents | validate input or decide risk |
| `services/analysis.py` | `analyze_incident(payload) -> Analysis` | persist anything |
| `database.py` | Connections, schema, `get_db` dependency | |
| `seed.py` | Synthetic demo incident | |
| `config.py` | Env-var settings, read at call time | |
| `errors.py` | `AppError`, `error_body()` | |

### The analysis seam

`analyze_incident` is the single place future detection plugs in. Today it is a placeholder: it returns `risk_status = "needs_review"`, a fixed recommended action, and evidence items that are the submitted facts (`source = "submitted"`). The result is computed once at creation and stored with the incident. Replacing it with real analysis should not change the router, the schemas' envelope, or the frontend's data flow.

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

No authentication, no real AI or detection, no behavioural history, no file upload/inspection, no external integrations (banking, WhatsApp), no payment processing, no migrations tooling.

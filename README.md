# TrustBreak

AI-assisted **trusted-channel financial fraud defense**. Instead of only asking *"is this sender a scammer?"*, TrustBreak checks whether a financial request is **consistent** with the sender's identity, communication channel, payment details, attachment characteristics and historical behaviour.

> **Status: hackathon prototype (v0.13.0) — Trust & Transaction Risk Intelligence. Detect the Trust Break — before the payment.** Incidents can be created, stored and viewed end to end. A deterministic, explainable risk assessment (Risk Engine 2.0: message, social-engineering, behaviour and static attachment evidence correlated into normalized signals with provenance and no double counting) can be run per incident; weights are uncalibrated prototype heuristics and the score is not a probability; the latest result is **saved with the incident** and drives its status in the detail page, list and dashboard. A human analyst can then record a **VERIFIED** or **REJECTED** decision with a reason, kept as an immutable audit trail; that decision never changes the risk assessment. It is decision support, not proof of fraud, and nothing is blocked or paid. Not a production banking system. All demo data is synthetic.

## Feature status

Only what exists in code is listed as implemented. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the plan.

| Status | Features |
|---|---|
| **Implemented** | **0.13.0:** counterfactual risk analysis (read-only what-ifs through the same Risk Engine); scenario simulator with 7 synthetic scenarios run through the real pipeline (DEMO MODE); independent verification workflow (NOT_STARTED / IN_PROGRESS / CONFIRMED / FAILED, append-only audit, never via the suspicious channel); forensic timeline from persisted events; analyst command-center dashboard with honest AI status; analyst incident workspace; printable incident report. Earlier: Incident create / list / detail; message extraction (Gemini, labelled deterministic fallback, offline demo mode); synthetic trusted identities (stable `sender_identity_id`, name fallback) with an EXPECTED-vs-OBSERVED identity card and an evidence graph; synthetic behavioural baseline 2.0 (deterministic synthetic history of 50-100 events per identity; amount ratio and percentile, new beneficiary, unusual channel and channel distribution, working-hours time/day, weekly frequency and burst velocity, each with evidence; `NOT_ENOUGH_BASELINE_DATA` instead of invented anomalies); structured social-engineering indicators (11 signals, each with quoted evidence and an AI / rule / fallback origin; evidence only, not scored yet); safe static attachment analysis (ZIP, executable, double-extension, path-traversal, nested / encrypted / bomb indicators); deterministic Risk Correlation Engine with explainable signals; immutable assessment history (v1, v2, ...) with `engine_version`; human case workflow (OPEN / VERIFIED / REJECTED) with immutable audit trail and each decision linked to the exact assessment it was based on; dashboard counts |
| **Partial** | Behaviour baseline (two synthetic identities; history is generated demo data, not real behaviour; time/day/velocity/frequency need an explicit `received_at` on incidents and are not yet scored by the risk engine); assessment storage (latest snapshot only, no history); attachment analysis (names and ZIP directory only, no hashing, contents never read) |
| **Planned** | Attachment analysis 2.0, authentication / roles, PDF generation, multilingual extraction (see roadmap) |
| **Experimental** | Gemini extraction: tested only against fakes and a mocked transport, never against the live API in this build |
| **Not implemented** | Authentication / roles, payment or bank integration, threat-intelligence lookups, multilingual extraction, any machine-learning model |

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite 6 + Tailwind CSS 4 + React Router |
| Backend | Python + FastAPI (REST, JSON) |
| Database | SQLite (standard-library `sqlite3`, no ORM) |

## Repository layout

```
frontend/   React app (Vite dev server on :5173, proxies /api to the backend)
backend/    FastAPI app (uvicorn on :8000) + tests
data/       SQLite database file is created here at first start (git-ignored)
docs/       PROJECT_STATE, ROADMAP, ARCHITECTURE, CHANGELOG, DEMO_SCENARIO
```

## Prerequisites

- Python 3.10 or newer
- Node.js 18 or newer (20+ recommended) and npm

## Run it locally

Use **two terminals**. Start the backend first.

### 1. Backend (terminal 1)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

On first start the backend creates `data/trustbreak.db` and inserts the synthetic demo incident. Check it:

- Health: <http://127.0.0.1:8000/api/health>
- Interactive API docs: <http://127.0.0.1:8000/docs>

### 2. Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. You should see the dashboard with one incident (the demo scenario).

## AI message analysis (optional)

The incident detail page has a **Message Analysis** card (extracts authority, amount, beneficiary, urgency, secrecy, deadline and financial intent from the message; extraction only, not a fraud decision). It works with no setup in clearly labelled **demo mode** (rule-based, not AI).

**Gemini (primary AI provider).** Copy `.env.example` to `.env`, set `GEMINI_API_KEY` (create one at https://aistudio.google.com/apikey), keep `TRUSTBREAK_AI_PROVIDER=gemini`, and put it in `backend/.env` (git-ignored; loaded automatically at startup, no export needed; variables already exported in your shell take precedence). The model is `TRUSTBREAK_AI_MODEL` (default `gemini-3.8-flash`). Then `pip install -r requirements.txt` (adds `google-genai`).

| Variable | Meaning |
|---|---|
| `TRUSTBREAK_AI_PROVIDER` | `gemini` / `mock` / `anthropic` (legacy) |
| `GEMINI_API_KEY` | Gemini key; read from the environment by the backend only, never sent to the browser |
| `TRUSTBREAK_AI_MODEL` | Model name for the selected provider; empty = that provider's default |
| `TRUSTBREAK_AI_MODE` | `auto` (default, fall back to demo), `ai` (error instead of fallback), `mock` (force offline demo) |
| `TRUSTBREAK_AI_TIMEOUT_SECONDS` | 1-120, default 20 |
| `ANTHROPIC_API_KEY` | Legacy; only needed with `TRUSTBREAK_AI_PROVIDER=anthropic` |

**Precedence:** `TRUSTBREAK_AI_MODE=mock` always forces offline demo; otherwise `TRUSTBREAK_AI_PROVIDER` decides; if it is unset, `GEMINI_API_KEY` selects Gemini, else a lone `ANTHROPIC_API_KEY` selects Anthropic (legacy setups), else Gemini is the default (and with no key the app falls back to the demo extractor).

**Offline:** `TRUSTBREAK_AI_PROVIDER=mock` - no key, no network.

**Fallback is always labelled.** If the key is missing or rejected, the free-tier limit is hit (HTTP 429), the request fails or times out, or the reply is not valid JSON for the schema, then in the default `auto` mode the existing deterministic extractor runs and the card says *"Gemini unavailable — deterministic fallback used"* with the reason and a failure label. The result carries `analysis_state: "fallback"` and a `failure_kind` (`quota_exhausted`, `auth_error`, `model_not_found`, `timeout`, `service_unavailable`, `unreachable`, `http_error`, `empty_response`, `invalid_response`, `not_configured`, `sdk_missing`, `unexpected`). The four states are `ai`, `fallback`, `mock` (offline demo chosen on purpose) and `skipped`. Mock output is never presented as AI-generated, the risk score is identical whichever extractor ran, and the risk assessment records which one was used. In `ai` mode a failure is an error, never a substitute.

**Gemini only extracts fields from the message text.** It does not score risk, decide fraud, call tools, browse URLs or see attachments; the deterministic risk engine remains authoritative.

## API

All responses share one envelope.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/incidents` | Create an incident (returns `201`) |
| `GET` | `/api/incidents?limit=100&offset=0` | List incidents, newest first |
| `GET` | `/api/incidents/{id}` | Incident detail |
| `GET` | `/api/identities` | List the synthetic trusted identities (read-only; fictional demo data) |
| `GET` | `/api/identities/{identity_id}` | One identity with its baseline summary and historical activity from stored incidents |
| `GET` | `/api/scenarios` | The 7 synthetic demo scenarios (inputs only, no expected scores) |
| `POST` | `/api/scenarios/{id}/load` | Create a labelled synthetic incident from a scenario and run the real risk pipeline on it |
| `GET` | `/api/dashboard` | Read-only command-center aggregates (KPIs, distribution, categories, active incidents, system status) |
| `GET` | `/api/incidents/{id}/counterfactuals` | "What would reduce the risk?": read-only what-if simulations that re-run the SAME Risk Engine on the latest stored assessment with one evidence group removed (before/after score, level, action). Never persisted, never changes the incident or assessment history |
| `GET` | `/api/incidents/{id}/verification` | Independent-verification state (NOT_STARTED / IN_PROGRESS / CONFIRMED / FAILED), recommended methods (never the suspicious channel) and its audit events |
| `POST` | `/api/incidents/{id}/verification` | Append a verification event `{action: START\|CONFIRM\|FAIL, method, reason, analyst_name}`. Separate from the risk assessment and from the final case decision; only when the latest assessment recommends VERIFY or HOLD_PAYMENT |
| `GET` | `/api/incidents/{id}/timeline` | Forensic timeline built only from persisted records (incident, assessments, verification and case audit rows); timestamps are never invented |
| `GET` | `/api/incidents/{id}/report` | Printable incident report (self-contained HTML, 14 sections; print or "Save as PDF" in the browser). Read-only; every value is HTML-escaped; no secrets |
| `GET` | `/api/incidents/{id}/trust-graph` | Evidence graph (nodes / edges) and EXPECTED-vs-OBSERVED comparison, derived from the identity baseline, behaviour checks and the latest stored assessment. Read-only; scores nothing |
| `POST` | `/api/incidents/{id}/analyze-message` | Extract entities / financial intent from the incident's message (AI or labelled demo mode; no fraud decision) |
| `POST` | `/api/incidents/{id}/analyze-behaviour` | Compare the request with the sender's synthetic behaviour profile (amount / beneficiary / channel / distribution / time / day / frequency / velocity signals with evidence and a synthetic baseline summary; no fraud decision; optional `received_at` on incident create enables time-based checks) |
| `POST` | `/api/incidents/{id}/analyze-attachment` | Safe static analysis of an uploaded file (multipart field `file`; never executed, extracted or stored); structural evidence, not a malware verdict |
| `GET` | `/api/incidents/{id}/assessments` | Assessment history, oldest first (v1..vN summaries; immutable) |
| `GET` | `/api/incidents/{id}/assessments/{version_number}` | One historical assessment with its full stored evidence |
| `POST` | `/api/incidents/{id}/analyze-risk` | Correlate message, behaviour and (optional multipart `file`) attachment evidence into heuristic risk points, a level and a recommended action, then **append it as a new immutable assessment version** (v1, v2, ...; `persisted: false` and not saved if message analysis was unavailable); prototype, not proof of fraud, blocks nothing. Attachment bytes are never stored |
| `GET` | `/api/incidents/risk-summary` | Counts of incidents per persisted risk level (critical / high / medium / low) and not assessed |
| `POST` | `/api/incidents/{id}/decision` | Record an analyst decision `{decision: VERIFIED\|REJECTED, reason, analyst_name}` for an OPEN case; appends an immutable audit row. Workflow record only: never changes the risk assessment and never touches a payment. `409 case_already_closed` if already decided |
| `GET` | `/api/incidents/case-summary` | Counts of cases per workflow status (open / verified / rejected) |
| `GET` | `/api/health` | Liveness check; reports the application version (`app.__version__`) |

```jsonc
// success
{ "success": true, "data": { ... }, "meta": { ... } }          // meta only on lists
// failure
{ "success": false, "error": { "code": "validation_error", "message": "...", "details": [{ "field": "amount", "message": "..." }] } }
```

Error codes: `validation_error` (422), `not_found` (404), `case_already_closed` (409), `method_not_allowed` (405), `internal_error` (500), plus `ai_not_configured` (503), `ai_unavailable` / `ai_invalid_response` (502) from the message-analysis endpoint in `TRUSTBREAK_AI_MODE=ai` (in the default `auto` mode these failures become a labelled deterministic fallback instead; in `ai` mode the envelope `details` carries `[{"failure_kind": ...}]`). Attachment endpoints add `attachment_missing`, `empty_file`, `filename_too_long` (400) and `file_too_large` (413).

Try it from the command line:

```bash
curl http://127.0.0.1:8000/api/incidents
curl -X POST http://127.0.0.1:8000/api/incidents -H "Content-Type: application/json" -d '{
  "sender_name": "Priya Nair", "sender_role": "Finance Controller", "sender_known": true,
  "channel": "Email", "amount": 250000, "beneficiary_name": "Acme Supplies",
  "beneficiary_is_new": false, "message": "Please process this invoice today."
}'
```

## Tests

```bash
# Backend (from backend/, venv active)
pip install -r requirements-dev.txt        # adds httpx, needed for the HTTP-level tests
python -m unittest discover -s tests -t . -v

# Frontend production build check (from frontend/)
npm run build
```

## Configuration (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `TRUSTBREAK_DB_PATH` | `<repo>/data/trustbreak.db` | SQLite file location |
| `TRUSTBREAK_SEED_DEMO` | `1` | Set to `0` to skip inserting the demo incident on an empty database |
| `TRUSTBREAK_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins |

The AI variables (`TRUSTBREAK_AI_PROVIDER`, `GEMINI_API_KEY`, `TRUSTBREAK_AI_MODEL`, `TRUSTBREAK_AI_MODE`, `TRUSTBREAK_AI_TIMEOUT_SECONDS`) are described in *AI message analysis* above.

**Reset the data:** stop the backend, delete `data/trustbreak.db`, start it again.

## Troubleshooting

- **Dashboard shows "Cannot reach the TrustBreak API"** - the backend is not running on port 8000. Start it (step 1) and click *Try again*.
- **Port already in use** - run uvicorn with another port (`--port 8001`) and change the proxy `target` in `frontend/vite.config.js` to match.
- **`pip` or `npm` cannot download packages** - check that your network allows PyPI and the npm registry.

## Project documents

See [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) for what works and what is known to be unverified, [`docs/ROADMAP.md`](docs/ROADMAP.md) for the planned sequence, and [`docs/DEMO_SCENARIO.md`](docs/DEMO_SCENARIO.md) for the demo walkthrough.

# TrustBreak

AI-assisted **trusted-channel financial fraud defense**. Instead of only asking *"is this sender a scammer?"*, TrustBreak checks whether a financial request is **consistent** with the sender's identity, communication channel, payment details, attachment characteristics and historical behaviour.

> **Status: hackathon prototype (v0.7.0).** Incidents can be created, stored and viewed end to end. A deterministic, explainable risk assessment (message + behaviour + attachment evidence) can be run per incident; the latest result is **saved with the incident** and drives its status in the detail page, list and dashboard. A human analyst can then review the recommendation and record a **VERIFIED** or **REJECTED** decision with a reason, kept as an immutable audit trail (v0.7.0); that decision never changes the risk assessment. It is decision support, not proof of fraud, and nothing is blocked or paid. Not a production banking system. All demo data is synthetic.

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

The incident detail page has an **AI Message Analysis** card (extracts authority, amount, beneficiary, urgency, secrecy, deadline and financial intent from the message; extraction only, not a fraud decision). It works with no setup in clearly labelled **demo mode** (rule-based, not AI). For real AI, copy `.env.example`, set `ANTHROPIC_API_KEY`, and export the variables before starting the backend (`set -a; source .env; set +a`). `TRUSTBREAK_AI_MODE=auto|ai|mock` controls fallback behaviour.

## API

All responses share one envelope.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/incidents` | Create an incident (returns `201`) |
| `GET` | `/api/incidents?limit=100&offset=0` | List incidents, newest first |
| `GET` | `/api/incidents/{id}` | Incident detail |
| `POST` | `/api/incidents/{id}/analyze-message` | Extract entities / financial intent from the incident's message (AI or labelled demo mode; no fraud decision) |
| `POST` | `/api/incidents/{id}/analyze-behaviour` | Compare the request with the sender's synthetic behaviour profile (amount / beneficiary / channel signals; no fraud decision) |
| `POST` | `/api/incidents/{id}/analyze-risk` | Correlate message, behaviour and (optional multipart `file`) attachment evidence into heuristic risk points, a level and a recommended action, then **save it as the incident's latest assessment** (`persisted: false` and not saved if message analysis was unavailable); prototype, not proof of fraud, blocks nothing. Attachment bytes are never stored |
| `GET` | `/api/incidents/risk-summary` | Counts of incidents per persisted risk level (critical / high / medium / low) and not assessed |
| `POST` | `/api/incidents/{id}/decision` | Record an analyst decision `{decision: VERIFIED\|REJECTED, reason, analyst_name}` for an OPEN case; appends an immutable audit row. Workflow record only: never changes the risk assessment and never touches a payment. `409 case_already_closed` if already decided |
| `GET` | `/api/incidents/case-summary` | Counts of cases per workflow status (open / verified / rejected) |
| `GET` | `/api/health` | Liveness check |

```jsonc
// success
{ "success": true, "data": { ... }, "meta": { ... } }          // meta only on lists
// failure
{ "success": false, "error": { "code": "validation_error", "message": "...", "details": [{ "field": "amount", "message": "..." }] } }
```

Error codes: `validation_error` (422), `not_found` (404), `case_already_closed` (409), `method_not_allowed` (405), `internal_error` (500), plus `ai_not_configured` (503), `ai_unavailable` / `ai_invalid_response` (502) from the message-analysis endpoint in `TRUSTBREAK_AI_MODE=ai`.

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

**Reset the data:** stop the backend, delete `data/trustbreak.db`, start it again.

## Troubleshooting

- **Dashboard shows "Cannot reach the TrustBreak API"** - the backend is not running on port 8000. Start it (step 1) and click *Try again*.
- **Port already in use** - run uvicorn with another port (`--port 8001`) and change the proxy `target` in `frontend/vite.config.js` to match.
- **`pip` or `npm` cannot download packages** - check that your network allows PyPI and the npm registry.

## Project documents

See [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) for what works and what is known to be unverified, [`docs/ROADMAP.md`](docs/ROADMAP.md) for the planned sequence, and [`docs/DEMO_SCENARIO.md`](docs/DEMO_SCENARIO.md) for the demo walkthrough.

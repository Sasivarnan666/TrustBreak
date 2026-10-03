# Project state

_Last updated: 2026-10-03 · Version 0.2.0 (foundation + AI message extraction)_

## What was implemented

A runnable full-stack foundation, flow: **React form → FastAPI → SQLite → dashboard / list / detail**.

- Backend: `POST /api/incidents`, `GET /api/incidents`, `GET /api/incidents/{id}`, plus `GET /api/health`; Pydantic validation; one JSON envelope for success and errors; SQLite schema created on startup; synthetic demo incident seeded when the table is empty.
- Frontend: Dashboard (KPIs, recent incidents, channel breakdown, analysis-engine notice), Incident list (search), Incident detail (status, summary strip, recommended action, message, evidence, sender, payment, attachment), Create incident form (client + server validation, "Load demo scenario"), loading / error / empty states, 404 page.
- Placeholder analysis: every incident is `needs_review`, gets one fixed recommended action, and its evidence is the submitted facts. It is labelled "placeholder" in the API and the UI. **No AI, scoring or detection exists.**
- Docs: README, ARCHITECTURE, ROADMAP, CHANGELOG, DEMO_SCENARIO, this file.

## Feature added in 0.2.0: AI message entity & financial-intent extraction

Converts an incident's free-text message into validated structured data (`claimed_authority`, `requested_action`, `payment_amount`, `currency`, `beneficiary`, `urgency_level`, `secrecy_indicator`, `organization`, `deadline`, `financial_intent`, `extracted_entities`, `confidence`). **Extraction only: no risk score, no risk level, no fraud decision** (every result carries `is_final_decision: false`). The incident's stored placeholder analysis (`needs_review`) is unchanged.

- **API added:** `POST /api/incidents/{id}/analyze-message` (no body). Computed on demand and **not stored** (no schema change). Errors use the existing envelope: `404 not_found`, `422` bad id, `503 ai_not_configured`, `502 ai_unavailable` / `ai_invalid_response` (the last three only in `TRUSTBREAK_AI_MODE=ai`).
- **Service seam:** `analyze_message(message) -> MessageAnalysis` in `backend/app/services/message_analysis/`. A future risk engine imports this and consumes `MessageAnalysis.extraction`; it never talks to an LLM.
- **Modes (always labelled in the result and the UI):** `ai` (real model, output passed strict validation), `mock` (deterministic regex demo rules, **not AI**, with a `fallback_reason`), `skipped` (empty message, nothing ran).
- **AI provider / configuration:** Anthropic Messages API over stdlib `urllib` (no new dependency). Env vars (see `.env.example`): `ANTHROPIC_API_KEY`, `TRUSTBREAK_AI_MODE` (`auto` default / `ai` / `mock`), `TRUSTBREAK_AI_MODEL` (default `claude-sonnet-5-5`), `TRUSTBREAK_AI_TIMEOUT_SECONDS` (default 20). No key is hard-coded; `.env` is git-ignored. The app reads real environment variables only (no `.env` loader): `set -a; source .env; set +a`.
- **Mock / fallback behaviour:** `auto` with no key -> mock (reason "No AI API key is configured."). `auto` with AI network failure or malformed/invalid reply -> mock, labelled, reason names the failure. `ai` mode never falls back: it returns the error. `mock` mode never touches the network. Mock confidence is a rule-coverage heuristic, not model certainty (stated in `notes` and the UI).
- **Security handling:** the message is untrusted data, sent only in the user turn between per-request random delimiters; the system prompt says to treat it as data and ignore embedded instructions; the model has no tools; URLs/emails in the text are recorded as strings and never fetched or followed; the reply must be a bare JSON object (optionally in a code fence) and is validated against a strict schema (exact key set, enums, bool/number type checks, ranges, length limits, entity types allow-listed). Unknown keys such as an injected `risk_level` are rejected. Raw model output is never returned to the client or put in error messages.
- **Frontend:** new `MessageAnalysisCard` on the incident detail page ("AI Message Analysis", button-triggered, so no API cost on page load) showing authority, action, amount, beneficiary, urgency, secrecy, organization, deadline, financial intent, confidence and entities, with a mode badge and an "extracted information, not a fraud decision" notice.

### Files added
`backend/app/services/message_analysis/{__init__,schema,prompt,ai_provider,mock_extractor,service}.py`, `backend/tests/test_message_analysis.py`, `backend/tests/test_message_analysis_api.py`, `frontend/src/components/MessageAnalysisCard.jsx`, `.env.example`.

### Files modified
`backend/app/config.py` (AI settings getters), `backend/app/schemas.py` (response models appended), `backend/app/routers/incidents.py` (one endpoint), `frontend/src/api/client.js` (`analyzeMessage`), `frontend/src/pages/IncidentDetail.jsx` (card inserted), `README.md`, and these docs.

### Verification of this feature (sandbox had no network, no pydantic/FastAPI, no npm packages)
| Check | Result |
|---|---|
| `tests/test_message_analysis.py`: 25 tests (normal / urgent / CEO / INR amounts / secrecy / no financial request / empty / malformed AI reply / no key + provider-down fallback / injection-style input / schema rejections / config) | **Run - 25 passing** |
| Synthetic CEO example through the service in mock mode | **Run - matches the specified output** (confidence 0.90 vs the 0.92 in the brief; mock heuristic) |
| AI path with an injected fake client (valid, fenced, malformed, provider error, `ai`-only mode) | **Run - passing** (no real AI provider was called; no key available) |
| Frontend: new/changed files parse; `MessageAnalysisView` rendered to HTML with real service output (mock, ai, skipped) | **Run - passing** (react-dom/server + esbuild; not a browser) |
| `tests/test_message_analysis_api.py` (7 HTTP tests incl. endpoint, 404, 422, 405, 503, 502, existing endpoints unchanged) | **Written, NOT run** (skip without FastAPI/httpx) |
| Real call to the Anthropic API | **NOT run** (no key, no network) |
| `npm run build`, browser rendering, running server | **NOT run** |
| Existing `test_core.py` / `test_api.py` | **Cannot run here** (import pydantic/FastAPI; same 2 import errors on the untouched baseline) |

## Current architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). In short: `frontend/` (React + Vite + Tailwind) talks only to `backend/` (FastAPI) over REST; the backend owns a single SQLite file in `data/`. The only seam intended for future intelligence is `backend/app/services/analysis.py`.

## Verification status (read this first)

The build environment could **not** reach PyPI or the npm registry (HTTP 403 `host_not_allowed`), so FastAPI, uvicorn, React, Vite and Tailwind were never installed there. What was and was not checked:

| Area | Status |
|---|---|
| Backend: validation, placeholder analysis, SQLite repository, seeding (23 `unittest` tests) | **Run - passing** |
| Backend: all Python files compile | **Run - passing** |
| Frontend: every `.js`/`.jsx` file parses (TypeScript compiler, JSX enabled) | **Run - passing** |
| Frontend: form validation, API-client error handling, and rendering of the dashboard / table / detail / loading / error / empty views against API-shaped JSON generated by the real backend code (19 ad hoc checks, stubbed router, React 19, not committed) | **Run - passing** |
| FastAPI app start-up, HTTP routes, error-envelope handlers, CORS | **NOT run** (10 tests in `backend/tests/test_api.py` are written and skip without FastAPI/httpx) |
| `npm install`, `npm run dev`, `npm run build`, Tailwind output | **NOT run** |
| Visual appearance in a real browser; Vite proxy to the backend | **NOT run** |

**Therefore the claim "the application runs" is not yet established.** The first step on a machine with network access is below.

## Working features (by code and the checks above)

- Create an incident with sender, channel, amount, beneficiary, message, optional attachment metadata; invalid input is rejected with field-level messages
- Persist to SQLite and read back (round trip tested)
- List newest first; detail view with all sections
- Indian rupee formatting (`₹18,50,000`) on both sides
- Demo incident seeded once

## Known issues and limitations

**Message extraction (0.2.0):**
- Real AI mode has never been exercised against the live API in this build; the prompt and the output validation were tested only with a fake client. Strict validation means an imperfect real reply falls back to labelled demo mode (or errors in `ai` mode) instead of being repaired.
- Demo (mock) rules are English-only keyword/regex rules: amounts need a currency marker (`₹`, `Rs`, `INR`, `rupees`, `$`...), `claimed_authority` needs an "I am / this is / from the <title>" phrasing, it can be fooled by negation and paraphrase, and when several amounts appear it reports the largest.
- AI output is validated for shape, not truth: nothing checks that `payment_amount` or `beneficiary` actually appear in the message.
- Results are not persisted; each click re-runs the analysis (and costs one API call in AI mode). There is no rate limiting.
- Existing app version string (`/api/health`, FastAPI) still reads 0.1.0.

**Foundation (0.1.0):**

1. **Unverified runtime** (see table above): HTTP layer, npm toolchain and browser rendering have never been executed together.
2. `frontend/package.json` version ranges (React 18, Vite 6, `@vitejs/plugin-react` 4, Tailwind 4, React Router 6) were chosen without registry access; if `npm install` reports a peer conflict, adjust that range rather than the code.
3. Placeholder analysis is identical for every incident; the "Needs review" status carries no risk information.
4. Dashboard KPIs are computed in the browser from at most 500 incidents (`limit=500`); there is no pagination UI.
5. No authentication, edit, delete or status workflow.
6. Attachment size is entered in KB in the form and stored as bytes; attachments are metadata only.
7. Schema changes need a manual database reset (no migrations tool).
8. Styling uses system fonts (no web-font download).

## Exact next recommended task

**Step 0 - verify on a networked machine (about 10 minutes):** follow the README run steps, then run `python -m unittest discover -s tests -t . -v` after `pip install -r requirements-dev.txt` (all 33 tests should run, none skipped), and `npm run build` in `frontend/`. Fix anything that fails before adding features. Update the table above with the results.

**Step 1 - next feature (after Step 0): trusted sender profiles and a deterministic channel-consistency check.** Add a `trusted_profiles` table (sender, role, expected channels, expected contact), seed one for the demo CEO, and have `analyze_incident` compare the incident's channel and contact against it, returning explainable evidence items (`source = "analysis"`) and a risk status. Rules only for the comparison. It should read `claimed_authority` (and `requested_action`) from `analyze_message(...).extraction` and compare the claimed role with the profile; it must not call an LLM itself. See [ROADMAP.md](ROADMAP.md).

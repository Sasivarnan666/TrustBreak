# Changelog

## 0.2.0 - 2026-10-03 - AI message entity & financial-intent extraction

### Added
- `backend/app/services/message_analysis/`: `analyze_message(message) -> MessageAnalysis` with strict schema validation (`schema.py`), prompt-injection-aware prompt (`prompt.py`), Anthropic client over stdlib `urllib` (`ai_provider.py`), deterministic demo extractor (`mock_extractor.py`) and the orchestrating service (`service.py`).
- `POST /api/incidents/{id}/analyze-message` returning the validated extraction with its mode (`ai` / `mock` / `skipped`), notes and `is_final_decision: false`. Not persisted; no schema change.
- Config: `ANTHROPIC_API_KEY`, `TRUSTBREAK_AI_MODE`, `TRUSTBREAK_AI_MODEL`, `TRUSTBREAK_AI_TIMEOUT_SECONDS`; `.env.example`.
- Frontend: "AI Message Analysis" card on the incident detail page (on-demand, mode badge, "not a fraud decision" notice).
- Tests: 25 service tests (run), 7 HTTP tests (written, need FastAPI).

### Notes
- Extraction only. No risk scoring, risk levels, blocking or other roadmap items were implemented; the incident's placeholder analysis is unchanged.
- Without an API key the app runs in clearly labelled demo (rule-based) mode.

## 0.1.0 - 2026-10-03 - Foundation

### Added
- Project structure: `frontend/`, `backend/`, `data/`, `docs/`, root `README.md`, `.gitignore`.
- **Backend (FastAPI + SQLite)**
  - `POST /api/incidents`, `GET /api/incidents` (with `limit`/`offset`), `GET /api/incidents/{id}`, `GET /api/health`.
  - Pydantic request validation (required fields, length limits, positive whole-rupee amount, allowed channels, attachment details require a file name, unknown fields rejected).
  - Uniform JSON envelope for success and failure; handlers for validation (422), not found (404), HTTP errors and unexpected errors (500).
  - SQLite `incidents` table created on startup; stdlib `sqlite3` repository; synthetic demo incident seeded when empty.
  - Placeholder analysis service (`needs_review`, fixed recommended action, submitted facts as evidence).
  - Environment-variable configuration (`TRUSTBREAK_DB_PATH`, `TRUSTBREAK_SEED_DEMO`, `TRUSTBREAK_CORS_ORIGINS`).
  - Tests: 23 `unittest` tests (validation, analysis, repository, seeding) and 10 HTTP-level tests that run when FastAPI and httpx are installed.
- **Frontend (React + Vite + Tailwind)**
  - Dashboard, incident list with search, incident detail, create-incident form with client-side validation and server error mapping, "Load demo scenario" button.
  - Loading, error (with retry) and empty states; 404 page.
  - API client with typed errors; Indian-rupee, date and file-size formatting.
- **Docs**: PROJECT_STATE, ROADMAP, ARCHITECTURE, CHANGELOG, DEMO_SCENARIO.

### Notes
- Analysis is a placeholder; no AI, detection, upload, auth or integrations.
- The HTTP layer, npm install/build and browser rendering were not executed in the build environment (package registries were blocked). See PROJECT_STATE.

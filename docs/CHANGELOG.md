# Changelog

## 0.5.0 - 2026-10-03 - Risk Correlation Engine

### Added
- `backend/app/services/risk_correlation/`: `rules.py` (prototype weights, thresholds, action mapping), `engine.py` (`correlate_risk`, pure and stdlib-only), `service.py` (`assess_incident_risk`, runs the three analyzers then correlates). Deterministic and explainable; no LLM decides the score.
- Twelve signals in twelve categories (urgency, secrecy, financial intent, authority mismatch, payment / beneficiary / channel anomaly, executable content, document deception, deceptive filename, path traversal, other high-severity attachment finding); each category counts at most once, so duplicate findings cannot inflate the score. Heuristic risk points (displayed score capped at 100, uncapped sum reported as `raw_points`).
- Prototype thresholds LOW 0-19 / MEDIUM 20-39 / HIGH 40-69 / CRITICAL 70+ mapped to `PROCEED` / `VERIFY` / `VERIFY` / `HOLD_PAYMENT`. The engine only recommends; `payment_blocked` is always false.
- `trust_break_detected` + "TRUST BREAK DETECTED" headline when a HIGH/CRITICAL result combines at least two independent sources with at least one inconsistency with the trusted context.
- `POST /api/incidents/{id}/analyze-risk` (optional multipart `file` for attachment evidence; on demand, not stored, no schema change). Missing or unavailable inputs add no points and are reported in `inputs` and `notes`.
- Frontend: "TrustBreak Risk Assessment" card on the incident detail page (score, level, recommended action, "Why this was flagged" evidence cards, disclaimer); the attachment file chosen in Attachment Analysis is reused by the risk card.
- Tests: 51 unit tests and 6 HTTP tests (179 total, all passing).

### Notes
- Scores are heuristic risk points, not probabilities; thresholds are prototype values; behaviour data is synthetic; the assessment does not prove fraud and blocks nothing.
- `services/analysis.py` (the stored placeholder analysis) and every existing endpoint are unchanged.
- `is_final_decision` is `true` on this result (final pipeline output, per the feature brief); the three analyzers still return `false`.

## 0.4.0 - 2026-10-03 - Safe attachment analysis

### Added
- `backend/app/services/attachment_analysis/`: `config.py` (central extension denylist, document keywords, limits), `analyzer.py` (`analyze_attachment`, `AttachmentError`). Stdlib only; independent of message analysis, behaviour analysis and scoring.
- Checks: signature-based file type (name is not trusted), ZIP central-directory listing (members are never read or extracted), `executable_inside_archive`, `double_extension`, `document_with_executable_content`, `content_type_mismatch`, `executable_file`, `risky_extension`, `path_traversal`, `nested_archive`, `encrypted_entries`, `high_compression_ratio`, `invalid_archive`, `too_many_entries`, `long_entry_name`, `archive_not_inspected`.
- `POST /api/incidents/{id}/analyze-attachment` (multipart field `file`; analyzed in memory, never stored, no schema change). New dependency: `python-multipart`.
- Frontend: "Attachment Analysis" card on the incident detail page (file picker + findings, with a "structural analysis only" notice).
- `scripts/make_demo_attachment.py` builds the inert synthetic `RBI_Statement.zip`.
- Tests: 22 analyzer/safety tests (run), 10 HTTP tests (written, need FastAPI).

### Notes
- Every result carries `is_final_decision: false`; wording is "suspicious executable content detected", never a malware claim. Not connected to any risk score.

## 0.3.0 - 2026-10-03 - Behaviour baseline & anomaly detection

### Added
- `backend/app/services/behaviour/`: synthetic `BehaviourProfile` + demo registry (`profile.py`), deterministic `analyze_behaviour` (`analyzer.py`) and `analyze_incident_behaviour` convenience entry point. Stdlib only.
- Signals: amount above baseline (deviation = excess over typical maximum; high above 2x), `NEW_BENEFICIARY`, `UNUSUAL_CHANNEL`. Frequency documented as future work (`frequency_anomaly` always false, reported as not evaluated).
- `POST /api/incidents/{id}/analyze-behaviour` (on demand, not stored, no schema change).
- Frontend: "Behavioural Analysis" card on the incident detail page, labelled as behavioural signals, not a fraud verdict.
- Tests: 20 analyzer tests (run), 5 HTTP tests (written, need FastAPI).

### Notes
- Signals only: no risk score or verdict, not connected to `analyze_incident` or to message analysis. Synthetic data only.


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

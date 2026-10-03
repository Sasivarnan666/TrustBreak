# Changelog

## 0.7.1 (patch) - Gemini 503 / AFC diagnostic fix

Gemini provider only; risk engine, behaviour, attachment analysis, case workflow, weights and the extraction schema are untouched.

### Changed
- `providers/gemini.py`: `automatic_function_calling` is now explicitly disabled. The google-genai SDK enters its AFC code path by default even with no tools and logs "Direct use of automatic function calling (AFC) in Models.generate_content is not recommended"; that log was harmless noise (no tools, no function map, one request) but is now gone and "no AFC" is explicit.
- `providers/gemini.py`: SDK-native bounded retry (`HttpRetryOptions`, 3 attempts, 1-4 s backoff, status 500/502/503/504; 429 is not retried). The SDK does NOT retry unless `retry_options` is set, so previously a single 503 failed immediately. No custom retry loop. A final 503 still becomes `ProviderError -> ai_unavailable` (HTTP 502 from the API) and is never labelled as AI.

### Tests
- 7 new tests in `tests/test_ai_providers.py` (AFC disabled, no AFC warning logged, no function-calling fields in the request body, 503 -> `ai_unavailable`, final 503 after SDK retries, 503-then-success, 429 not retried). 323 total. No real Gemini call is made.

## 0.7.1 - 2026-10-03 - Provider-agnostic AI adapter (Gemini primary)

Not a feature: replaces the Anthropic-only message-extraction integration with a provider adapter. The risk engine, risk weights/thresholds/levels, correlation rules, case workflow, behaviour and attachment analysis, and the 12-field extraction schema are untouched.

### Added
- `services/message_analysis/providers/` (`base`, `gemini`, `anthropic`, `mock`): contract `analyze_message(text) -> MessageExtraction`. LLM providers implement only `complete(system, user)`; prompt, parsing and strict validation are shared, not duplicated.
- Gemini provider on the official `google-genai` SDK (new dependency, `google-genai>=2.28,<3.0`): one text-only call with JSON output and a response schema derived from the existing schema (`extraction_json_schema()`); no tools, no files, no attachment bytes. The reply is still validated by `validate_extraction`.
- Configuration: `TRUSTBREAK_AI_PROVIDER` (`gemini`/`mock`/`anthropic`), `GEMINI_API_KEY`, `TRUSTBREAK_AI_MODEL` (default per provider, `gemini-3.8-flash`, defined only in `config.py`). `TRUSTBREAK_AI_MODE` (`auto`/`ai`/`mock`) is preserved. Precedence: `MODE=mock` > `PROVIDER` > `GEMINI_API_KEY` > lone `ANTHROPIC_API_KEY` > `gemini`.
- Provenance fields on the message-analysis result and API response: `provider`, `requested_provider`, `is_fallback` (additive; `mode` and `extraction` unchanged).
- Tests: 42 new in `tests/test_ai_providers.py` (selection/precedence, config, missing key, valid structured reply, malformed JSON, schema failures, timeout/HTTP/SDK failure, blocked response, secret non-leakage, mock provider, real SDK over a mocked httpx transport, HTTP provenance, risk result identical for equivalent evidence, AST import boundaries) - 316 total. No test makes a real Gemini call.

### Changed
- Fallback wording: a missing key, failed or timed-out call, unparsable reply or schema failure now reports "Gemini analysis failed: ... Using demo/mock extraction (not AI)" (or the no-key equivalent). Mock output is never attributed to a model.
- Message Analysis card (title no longer says "AI"): "AI analysis - Gemini" (with the model name), "Demo mode - rule-based, not AI", or "Gemini unavailable - using demo extraction". It states that risk comes from the deterministic engine.
- `ai_provider.py` is now a compatibility shim over `providers/`. Existing API tests also clear `GEMINI_API_KEY`/`TRUSTBREAK_AI_PROVIDER` so a developer's real key can never trigger a live call from the suite.

### Notes
- Anthropic support is kept but no longer required or the default.
- No live Gemini call was made in this change (no key in the environment); see PROJECT_STATE.

## 0.7.0 - 2026-10-03 - Case workflow & analyst decision audit

### Added
- Human review after the risk assessment: workflow status `OPEN` (initial) / `VERIFIED` / `REJECTED`, kept separate from the risk level. `CRITICAL + OPEN` and `CRITICAL + VERIFIED` are both valid; the risk assessment is never read or changed by a decision.
- `case_actions` table (existing startup-schema convention, no migration framework): append-only audit rows (`incident_id, previous_status, new_status, decision, reason, analyst_name, created_at`) with CHECK constraints, a `BEFORE UPDATE` abort trigger and partial unique indexes (one decision and one `CASE_OPENED` per incident). Current status = latest row's `new_status`. Every new incident gets a `CASE_OPENED` row in the same transaction; older incidents are backfilled at startup (idempotent).
- `POST /api/incidents/{id}/decision` `{decision: VERIFIED|REJECTED, reason (10-1000, trimmed), analyst_name (2-80, trimmed)}`. Transition rules `OPEN -> VERIFIED|REJECTED` only; a closed case answers `409 case_already_closed`. Uses `BEGIN IMMEDIATE`; failure rolls back.
- `GET /api/incidents/{id}` adds `workflow_status`, `workflow_status_label`, `case_history`. `GET /api/incidents` rows add `workflow_status(_label)`. `GET /api/incidents/case-summary` returns `{total, open, verified, rejected}`.
- Layering `router -> services/case_workflow.py -> case_repository.py -> SQLite`; the risk engine does not import the workflow (AST-tested). `case_repository.py` and `case_workflow.py` existed unwired in the 0.6.0 archive and were completed.
- Frontend: Case review card (decision form, validation, feedback, disabled when closed), Case history timeline, Risk + Case badges on the detail header, a Case column in the incident list, Open / Verified / Rejected KPIs on the dashboard (risk KPIs kept).
- Tests: 58 new (28 DB/service, 30 HTTP) - 274 total.

### Notes
- A decision is an audit record, not a payment action. Nothing is approved, rejected, blocked, cancelled or executed, and the UI says "Analyst verified the request" / "Analyst rejected the case", never "TrustBreak verified".
- No authentication: `analyst_name` is free text. No reopening, comments or edits.
- Verification caveat: in the authoring sandbox FastAPI/httpx and Vite could not be installed (403), so the 30 HTTP tests and `npm run build` still need to be run on a networked machine. See PROJECT_STATE.

## 0.6.0 - 2026-10-03 - Persisted risk assessment & real incident status

### Added
- `risk_assessments` table (created by the existing startup schema, no migration framework): the LATEST assessment per incident, one row (`incident_id UNIQUE`), replaced on every run. Scalar columns for score, raw points, max score, level, recommended action, incident status, trust-break flag, headline, explanation, guidance, scoring method, disclaimer, `assessed_at` and `assessment_version`; JSON text for signals, category points, inputs, thresholds and notes.
- `backend/app/risk_repository.py`: `save_risk_assessment` (upsert, transactional, rejects unknown incidents and malformed results), `get_latest_risk_assessment`, `risk_summary` (SQL counts). The risk engine is unchanged and contains no SQL.
- `services/risk_correlation/incident_status.py`: LOW -> `proceed`, MEDIUM -> `verify`, HIGH -> `verify`, CRITICAL -> `hold_payment`; `not_assessed` when none exists.
- `POST /api/incidents/{id}/analyze-risk` now persists and returns the stored assessment (extra fields: `incident_id`, `incident_status`, `incident_status_label`, `assessment_version`, `assessed_at`, `persisted`).
- `GET /api/incidents/{id}` adds `risk_assessment` (null until assessed), `incident_status`, `incident_status_label`. `GET /api/incidents` rows add `incident_status(_label)`, `risk_level`, `risk_score`, `recommended_action(_label)`, `trust_break_detected`, `assessed_at` via a single LEFT JOIN (no N+1).
- `GET /api/incidents/risk-summary`: counts of total / critical / high / medium / low / not assessed from persisted assessments.
- Assessment version `0.6.0` stored with each snapshot.
- Frontend: the Risk Assessment card loads the stored result (no re-run needed after a refresh), shows "Not assessed" before a run, the assessment time and version, and "Run again" replaces the snapshot. Incident list shows risk level + recommended action or "Not assessed". Dashboard KPIs: total, critical, high, medium, low, not assessed. Detail header shows the persisted level.
- Tests: 37 new (216 total, 0 skipped).

### Changed
- The stored 0.1.0 placeholder (`needs_review` + fixed text) is no longer shown as a status anywhere in the UI. The API keeps `analysis` / `risk_status` unchanged for backward compatibility; before an assessment exists the detail page shows it only as a neutral "Intake note - placeholder, not a risk assessment".
- The v0.5.0 test "nothing is stored" was rewritten to its new meaning (the placeholder `analysis` block is untouched; the assessment is stored).

### Behaviour worth knowing
- If message analysis is unavailable (e.g. `TRUSTBREAK_AI_MODE=ai` without a key) the request still returns 200 as in 0.5.0, but the incomplete result is returned with `persisted: false` and is NOT saved; an earlier stored assessment stays as it was.
- Uploaded attachment bytes are analyzed in memory and never stored; only derived structured evidence (e.g. executable file names) is saved.
- `hold_payment` is a recommendation to a human. Nothing is blocked.

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

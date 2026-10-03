# Project state

_Last updated: 2026-10-03 · Version 0.6.0 (foundation + AI message extraction + behaviour baseline + safe attachment analysis + risk correlation engine + **persisted risk assessment & real incident status**) · 216/216 backend tests passing, frontend build passing_

## What was implemented

A runnable full-stack foundation, flow: **React form → FastAPI → SQLite → dashboard / list / detail**.

- Backend: `POST /api/incidents`, `GET /api/incidents`, `GET /api/incidents/{id}`, plus `GET /api/health`; Pydantic validation; one JSON envelope for success and errors; SQLite schema created on startup; synthetic demo incident seeded when the table is empty.
- Frontend: Dashboard (KPIs, recent incidents, channel breakdown, analysis-engine notice), Incident list (search), Incident detail (status, summary strip, recommended action, message, evidence, sender, payment, attachment), Create incident form (client + server validation, "Load demo scenario"), loading / error / empty states, 404 page.
- Placeholder analysis: every incident is `needs_review`, gets one fixed recommended action, and its evidence is the submitted facts. It is labelled "placeholder" in the API and the UI. **No AI, scoring or detection exists.**
- Docs: README, ARCHITECTURE, ROADMAP, CHANGELOG, DEMO_SCENARIO, this file.

_The two bullets above describe 0.1.0. Later versions add message extraction (0.2.0), behaviour signals (0.3.0), attachment analysis (0.4.0) and the on-demand Risk Correlation Engine (0.5.0, below). The **stored** placeholder analysis is unchanged; the risk assessment is computed on demand and not stored._

## Release verification pass (v0.4.0) - 2026-10-03

A verification-only pass. **No product code was changed and no feature was added.** Run in a clean environment with network access to PyPI and npm (Python 3.12.3, Node 22, npm 10), using a fresh virtualenv and the dependencies declared in `backend/requirements-dev.txt` (FastAPI 0.142.2, Starlette 1.7.0, pydantic 2.13.5, httpx 0.28.1, python-multipart 0.0.32, uvicorn 0.54.0).

### Tests run
| Check | Result |
|---|---|
| `python -m unittest discover -s tests -t . -v` (from `backend/`) | **122 run, 122 passed, 0 failed, 0 errors, 0 skipped** (first run in which the HTTP tests were not skipped) |
| Breakdown | test_core 23, test_api 10, test_message_analysis 25, test_message_analysis_api 7, test_behaviour 20, test_behaviour_api 5, test_attachment_analysis 22, test_attachment_analysis_api 10 |

### Build status
| Check | Result |
|---|---|
| `npm install` + `npm run build` (from `frontend/`) | **Passed** (Vite 6.4.3, 47 modules; installed: React 18.3.1, React Router 6.30.6, Tailwind 4.3.3, plugin-react 4.7.0). The version ranges chosen without registry access in 0.1.0 resolved with no peer conflict. |
| Vite dev server + `/api` proxy to the backend | **Passed** (`/api/health` through :5173 returned the backend response; `/src/main.jsx` served) |

### Features verified (real uvicorn process, temporary SQLite file, real HTTP)
| Feature | Result |
|---|---|
| Backend starts; DB created and demo incident seeded | **Verified** |
| `GET /api/health` | **Verified** (still reports version `0.1.0`, see issues) |
| Incident creation (`POST /api/incidents`, 201), listing, detail; 404 and 422 envelopes | **Verified** |
| `POST /analyze-message` (demo mode, no API key) | **Verified**: labelled `mock`, INR 18,50,000 extracted, `is_final_decision: false` |
| `POST /analyze-behaviour` | **Verified**: demo CEO case gives amount deviation 8.25, new beneficiary, unusual channel; unknown sender gives `profile_found: false` |
| `POST /analyze-attachment` with the synthetic `RBI_Statement.zip` | **Verified**: archive inspected, 3 entries (`Statement.pdf`, `Update.exe`, `helper.dll`), `contains_executable: true`, `executable_files: [Update.exe, helper.dll]`, findings `executable_inside_archive` x2 (high) and `document_with_executable_content` (medium), `is_final_decision: false`. Nothing was executed or extracted; the files were sent as bytes only. |
| Attachment error envelopes (no file, empty file, unknown incident) | **Verified** (`attachment_missing`, `empty_file`, `not_found`) |
| Frontend shows all three analysis cards | **Verified by server-side render, not in a browser**: the three views were rendered with live API responses (all expected values present), and the real incident detail view mounts all three cards. |

### Architecture check
- `message_analysis`, `behaviour` and `attachment_analysis` import nothing from each other, from `services/analysis.py`, or from `app.*` (static import scan). `services/analysis.py` imports none of them. Only `routers/incidents.py` imports them, one endpoint each.
- None of the three outputs contains a score, risk level or verdict field (checked on live responses and by source scan); each returns `is_final_decision: false`.
- No risk correlation engine exists. The planned shape is unchanged: `Message + Behaviour + Attachment -> Risk correlation engine` (not built at the time of that pass; built in 0.5.0).

### Remaining known issues (found or confirmed in this pass; none fixed, none blocking)
1. **Not tested in a real browser.** No browser was available; frontend rendering was checked by server-side render only. Click behaviour of the three buttons, the file picker and visual layout are unverified.
2. **Real AI mode never exercised** against the live Anthropic API (no key); only the labelled demo mode and a fake client were tested.
3. **Version strings stale:** `/api/health` and the FastAPI app report `0.1.0`; `frontend/package.json` is `0.1.0`.
4. **README stale:** the status banner says v0.1.0 and the API table omits `POST /api/incidents/{id}/analyze-attachment`.
5. **`npm audit`: 2 moderate advisories** in `react-router` / `react-router-dom` 6.x (SSR hydration `deserializeErrors`, GHSA-337j-9hxr-rhxg). The app is a client-side SPA and does not use SSR hydration; the only fix offered is a breaking upgrade to v7, so it was not applied.
6. **Demo-mode extraction limits** (documented in 0.2.0): for the seeded demo message `claimed_authority` is `null` because the message has no "I am the CEO" phrasing.
7. The limitations already listed per feature (behaviour frequency not implemented, `erp` channel can never match a form channel, ZIP entry contents never read, nothing persisted) are unchanged.

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

## Feature added in 0.3.0: Behaviour baseline & anomaly detection (COMPLETED)

Compares one payment request with a **synthetic** per-employee behaviour profile and returns structured anomaly **signals**. **Not a risk score or fraud verdict** (`is_final_decision: false`; no risk level in the output). Independent of message analysis and of `analyze_incident`; nothing is wired into the placeholder analysis or any score.

Flow: `Incident -> BehaviourProfile (lookup by sender name) -> analyze_behaviour -> structured anomaly result`.

### Behaviour profile structure (`services/behaviour/profile.py`)
`BehaviourProfile { employee_id, name, role, normal_channels[], known_beneficiaries[], historical_amounts[], typical_min_amount?, typical_max_amount?, request_frequency?, aliases[] }`. Typical min/max default to min/max of history. Two synthetic profiles in a code registry (no DB table, no schema change): `CEO-001` Arvind Rao (matches the seeded demo sender; channels email/erp; beneficiaries Vendor A/B/C; typical max INR 2,00,000; frequency low) and `CFO-001` Meera Iyer. Lookup is by sender name (case/space-insensitive). All data fictional.

### Anomaly rules (`services/behaviour/analyzer.py`)
| Check | Rule | Signal |
|---|---|---|
| Amount | `deviation = (amount - typical_max) / typical_max`, floored at 0. Any amount above the typical maximum is a signal; `deviation > 1.0` (over 2x the maximum) is **high**, otherwise **medium**. Amounts at or below the maximum are normal (unusually small amounts are not flagged). | `AMOUNT_ABOVE_BASELINE` |
| Beneficiary | Not in `known_beneficiaries` (case/space-insensitive exact match; the form's `beneficiary_is_new` flag is deliberately ignored, the profile is the source of truth). | `NEW_BENEFICIARY`, high |
| Channel | Not in `normal_channels` (case/space-insensitive). | `UNUSUAL_CHANNEL`, medium |
| Frequency | **Not implemented.** Needs per-sender request history (an architectural change). `frequency_anomaly` is always `false` and `checks.frequency.status = "not_evaluated"`; a note says so. | - |

Missing data never raises: no profile -> `profile_found: false`, no anomalies, a note; missing/non-positive amount or blank beneficiary/channel -> that check is `not_evaluated` and noted, the others still run. Worked example: INR 18,50,000 vs typical max INR 2,00,000 -> deviation 8.25 (= (18.5L - 2L) / 2L).

### API change
`POST /api/incidents/{id}/analyze-behaviour` (no body): same pattern as `analyze-message`; computed on demand, not stored. Errors use the existing envelope (`404 not_found`, `422` bad id, `405` for GET). Response `data`: `employee_id, profile_found, amount_anomaly, amount_deviation, new_beneficiary, channel_anomaly, frequency_anomaly, checks{amount,beneficiary,channel,frequency}, anomalies[{type,code,severity,message}], profile_summary, notes, is_final_decision`.

### Frontend
`BehaviourAnalysisCard` ("Behavioural Analysis", button-triggered) on the incident detail page, labelled "Behavioural signals" with a "not a fraud verdict" notice: channel (Normal / Unusual), amount (Within / Above baseline), beneficiary (Known / New), and the signal list (red = high, amber = medium).

### Files added
`backend/app/services/behaviour/{__init__,profile,analyzer}.py`, `backend/tests/test_behaviour.py`, `backend/tests/test_behaviour_api.py`, `frontend/src/components/BehaviourAnalysisCard.jsx`.

### Files modified
`backend/app/schemas.py` (behaviour response models appended), `backend/app/routers/incidents.py` (one endpoint), `frontend/src/api/client.js` (`analyzeBehaviour`), `frontend/src/pages/IncidentDetail.jsx` (card inserted), and the docs.

### Verification of this feature (same sandbox limits: no PyPI/npm access)
| Check | Result |
|---|---|
| `tests/test_behaviour.py`: 20 tests (normal/very high/moderate amount, known/new beneficiary, normal/unusual channel, combined, missing profile, missing beneficiary, missing amount, nothing provided, demo scenario, normal payment, lookup) | **Run - 20 passing** |
| Whole backend suite (`unittest discover`) | **Run - 90 tests, 0 failures, 22 skipped** (the skips are the FastAPI/pydantic-dependent tests, as before) |
| CEO INR 18,50,000 scenario and a normal payment through `analyze_incident_behaviour` | **Run - passing** (deviation 8.25; normal payment has no signals) |
| Existing message-analysis tests (25) | **Run - still passing** |
| `BehaviourAnalysisView` rendered with real analyzer output (CEO, normal, no profile) via react-dom/server + tsx | **Run - passing** (not a browser) |
| `tests/test_behaviour_api.py` (5 HTTP tests) | **Written, NOT run** (skip without FastAPI/httpx) |
| `npm run build`, running backend (`uvicorn`), browser rendering | **NOT run** (packages cannot be installed here) |

### Known limitations (behaviour baseline)
- Profiles are hard-coded synthetic demo data keyed by exact sender name; unknown senders get "no profile". No management UI or storage.
- Amount rule is a simple ratio to the profile maximum, not a statistical model; it does not use the median or spread of history and does not flag unusually small amounts.
- Beneficiary matching is exact after case/space normalization (no fuzzy matching: "Vendor A Ltd" would be new).
- Channel names come from the form (WhatsApp, Email, SMS, Phone call, Other); profile channel `erp` can never match a form channel.
- Frequency not implemented (see above). Results are not persisted and not connected to any score.
- Seeded demo beneficiary is "New Vendor X" (not exactly "Vendor X"); it is new either way.

## Feature added in 0.4.0: Safe attachment analysis (COMPLETED)

Statically inspects an uploaded file and returns structured, explainable evidence. **It never executes, extracts, stores or opens anything from the file**, and it makes no malware claim (`is_final_decision: false`; wording is "suspicious executable content detected"). It is independent of message analysis, behaviour analysis and risk scoring, and is **not** connected to any score.

### Supported checks (`services/attachment_analysis/`)
- File metadata: name, extension, declared content type, size, and type detected from signature bytes (PDF, ZIP, PE/ELF, PNG/JPEG/GIF, OLE, RAR, 7z, GZIP). The name alone is never trusted.
- ZIP: central directory only (`ZipFile.infolist()`): entry count, names, extensions, declared uncompressed size, executable-looking entries. `.docx/.xlsx/.pptx` are treated as documents, not archives.
- Central denylist (`config.py`): `.exe .dll .scr .com .msi` (executable), `.bat .cmd .ps1 .vbs .js .jse` (script), `.lnk` (shortcut).
- Findings: `executable_inside_archive`, `double_extension` (document ext then executable ext, in the file name or an entry), `document_with_executable_content` (document/finance-looking name + executable entry), `content_type_mismatch`, `executable_file`, `risky_extension`, `path_traversal`, `nested_archive`, `encrypted_entries`, `high_compression_ratio` / `large_uncompressed_size`, `invalid_archive` (corrupt ZIP), `too_many_entries`, `long_entry_name`, `archive_not_inspected` (RAR/7z/GZIP).
- Deterministic: findings sorted by severity, type, entry.

### Safety restrictions
No execution, no extraction, no member reads, no file writes by the analyzer, no shell/network/URL access, entry names stripped of control characters and length-bounded. Limits: upload 10 MiB (`TRUSTBREAK_MAX_UPLOAD_BYTES`, bounded read), 255-char names, 1000 entries inspected. Tests patch `subprocess`, `os.system`, `open` and `ZipFile.extract/read/open` to fail and assert the analysis still succeeds, and scan the module source for execution-related imports. The only disk use is Starlette's own transient multipart spool (files over 1 MiB), deleted after the request; uploaded content is never kept or run.

### API change
`POST /api/incidents/{id}/analyze-attachment`, multipart field `file`, standard envelope. Errors: `404 not_found`, `400 attachment_missing` (no file part, or incident has no attachment), `400 empty_file`, `400 filename_too_long`, `413 file_too_large`. A corrupt/unsupported file is a normal `200` with findings/notes. If the uploaded name differs from the recorded attachment name a note says so. No database change (the incident still stores metadata only). New dependency: `python-multipart`.

### Frontend
"Attachment Analysis" card on the incident detail page (only when the incident has an attachment): choose the file, click **Analyze file**; shows file name/type, archive status, file count, executable content, findings (🔴/🟠), and the notice "Structural analysis only - this does not prove that the file is malware." The Attachment card text was updated to match.

### Files added
`backend/app/services/attachment_analysis/{__init__,config,analyzer}.py`, `backend/tests/test_attachment_analysis.py`, `backend/tests/test_attachment_analysis_api.py`, `frontend/src/components/AttachmentAnalysisCard.jsx`, `scripts/make_demo_attachment.py`.

### Files modified
`backend/app/schemas.py` (attachment response models), `backend/app/routers/incidents.py` (endpoint), `backend/requirements.txt` (`python-multipart`), `frontend/src/api/client.js` (`analyzeAttachment`, FormData support), `frontend/src/pages/IncidentDetail.jsx`, docs (this file, CHANGELOG, ROADMAP, ARCHITECTURE, DEMO_SCENARIO).

### Verification of this feature (same sandbox: no PyPI/npm access)
| Check | Status |
|---|---|
| 22 analyzer + safety tests (normal PDF, normal ZIP, EXE, DLL, EXE+DLL, RBI scenario, double extensions, archive name, empty ZIP, corrupt ZIP, missing/empty input, unsupported type, long names/limits, path traversal, nested/encrypted/bomb, determinism, no-execution guards) | **Run - passing** |
| Whole backend suite: 122 tests discovered, 90 pass, 32 skipped (all HTTP tests, incl. 10 new ones, need FastAPI/httpx) | **Run - passing / skipped as stated** |
| `POST /analyze-attachment` over HTTP, multipart parsing, error envelope, backend start-up | **NOT run** (FastAPI cannot be installed here) |
| Frontend: new/changed `.js`/`.jsx` files parse (esbuild transform) | **Run - passing** |
| `npm install` / `npm run build`, rendering in a browser | **NOT run** (npm registry blocked, HTTP 403) |

### Known limitations (attachment analysis)
- Only ZIP is listed; RAR/7z/GZIP are detected but not opened. Nested archives are flagged, not recursed.
- Entry contents are never read, so a file inside a ZIP named `.pdf` that is really a program is not detected; only names and declared sizes are used. Declared sizes come from the archive and can be forged.
- No macro/script/URL inspection inside documents, no hashing or threat intelligence, no deceptive-Unicode (RTL override) or hidden-file checks (future work).
- The keyword list for "document-looking" names is small and English-only; the file must be re-uploaded for each analysis (nothing is stored); results are not persisted.
- Severity is a heuristic ordering of structural indicators, not a likelihood of malice.

## Feature added in 0.6.0: Persisted risk assessment & real incident status (COMPLETED)

When a risk assessment is run it is now **saved with the incident** and becomes the incident's security status. The correlation engine, its weights and thresholds are unchanged.

Flow: `message / behaviour / attachment analysis -> risk correlation (pure) -> risk_repository (SQL) -> incident API / list / dashboard`.

### Persistence design
- Table `risk_assessments` (created by `CREATE TABLE IF NOT EXISTS` at startup, like `incidents`; an existing 0.5.0 database simply gains the table, no migration tool). **One row per incident** (`incident_id UNIQUE`, `ON DELETE CASCADE`): the latest snapshot. Running the assessment again replaces it (`INSERT ... ON CONFLICT DO UPDATE`), so "latest" is trivially the row. No history is kept (see limitations).
- Columns: `risk_score, raw_points, max_score, risk_level (CHECK), recommended_action, incident_status, trust_break_detected, headline, explanation, recommended_action_guidance, scoring_method, disclaimer, assessed_at (UTC ISO-8601 Z), assessment_version`, plus JSON text: `signals_json, category_points_json, inputs_json, thresholds_json, notes_json`. Thresholds are stored with the snapshot so it stays interpretable if they change.
- `assessment_version` is the constant `ASSESSMENT_VERSION = "0.6.0"` in `risk_repository.py`. Bump it when weights, thresholds or the stored shape change.
- Code: `app/risk_repository.py` (save / get latest / summary), `app/repository.py` (incident detail attaches the assessment; the list uses one LEFT JOIN), `services/risk_correlation/incident_status.py` (pure mapping). The engine imports none of them (AST-tested).
- **Never stored:** uploaded attachment bytes. Only the structured result is saved (a test uploads a zip containing a marker and scans every column of every table). File names of executable entries appear in signal details, as before.

### Incident status mapping
| Risk level | Recommended action | Incident status |
|---|---|---|
| LOW | PROCEED | `proceed` |
| MEDIUM | VERIFY | `verify` |
| HIGH | VERIFY | `verify` |
| CRITICAL | HOLD_PAYMENT | `hold_payment` |
| no assessment | - | `not_assessed` ("Not assessed") |

`hold_payment` means TrustBreak **recommends** that a human holds the transaction pending independent verification. Nothing is blocked (`payment_blocked` is always false). The old stored `needs_review` is no longer used as a status by the UI or the dashboard.

### API changes
- `POST /api/incidents/{id}/analyze-risk`: runs the pipeline, **persists**, returns the stored assessment (superset of the 0.5.0 response plus `incident_id, incident_status, incident_status_label, assessment_version, assessed_at, persisted`). If message analysis is `unavailable` the 0.5.0 behaviour is kept (200 with the unavailable input flagged) but the result is returned with `persisted: false`, a note, and **is not saved**; any earlier stored assessment is untouched. A bad attachment still returns its error and saves nothing.
- `GET /api/incidents/{id}`: new `risk_assessment` (null if none), `incident_status`, `incident_status_label`. `analysis` is unchanged.
- `GET /api/incidents`: rows gain `incident_status, incident_status_label, risk_level, risk_score, recommended_action, recommended_action_label, trust_break_detected, assessed_at` (null / `not_assessed` when none). `risk_status` is kept for compatibility but is the legacy placeholder.
- `GET /api/incidents/risk-summary` (registered before `/{incident_id}`): `{total, critical, high, medium, low, assessed, not_assessed}` computed in SQL from persisted assessments only.

### Frontend changes
Risk card loads the persisted assessment from the incident (a refresh shows it without re-running), shows "Not assessed" + explanation before a run, the assessed time and version, "Run again" to replace the snapshot, and keeps the saved result visible if a re-run fails or returns an unsaved result. Detail header, incident list ("Risk" + "Recommended action" columns) and dashboard (six KPIs) use the persisted level; incidents without one show "Not assessed". Wording separates "risk assessment" (deterministic heuristic) from "recommended action" (decision support); the disclaimer is unchanged.

### Files added
`backend/app/risk_repository.py`, `backend/app/services/risk_correlation/incident_status.py`, `backend/tests/test_risk_persistence.py` (21 tests), `backend/tests/test_risk_persistence_api.py` (16 tests).

### Files modified
`backend/app/database.py`, `backend/app/schemas.py`, `backend/app/repository.py`, `backend/app/routers/incidents.py`, `backend/tests/test_risk_correlation_api.py` (one test rewritten for the new contract), `frontend/src/{lib/risk.js, components/StatusBadge.jsx, components/RiskAssessmentCard.jsx, pages/IncidentDetail.jsx, pages/IncidentList.jsx, pages/Dashboard.jsx, api/client.js}`, README and these docs.

### Verification of this feature
| Check | Result |
|---|---|
| `python -m unittest discover -s tests -t . -v` (clean venv, FastAPI/httpx installed) | **216 run, 216 passed, 0 failed, 0 skipped** (179 existing + 37 new) |
| `npm run build` | **Passed** (48 modules) |
| Live uvicorn on a temp SQLite file, real HTTP | demo incident: before = `risk_assessment null / Not assessed`; after `analyze-risk` = 85 CRITICAL / HOLD_PAYMENT / TRUST BREAK DETECTED / `hold_payment`; a fresh GET and a GET after **restarting the server** return the same assessment and `assessed_at`; list shows CRITICAL + Hold payment; summary `critical 1`. Normal payment: 10 LOW / PROCEED / `proceed`. |
| Server-side render of the changed views with live API payloads (react-dom/server, not a browser) | detail (persisted and not assessed), list and dashboard contain the expected text and none of "Needs review" / `needs_review` |
| Real browser run-then-refresh | **NOT run**: no browser could be installed in this session (Playwright download blocked, HTTP 403). The persistence half of that test is covered by HTTP-level tests and the live restart check; click behaviour and layout are unverified. |
| Real Anthropic API | Not run (no key); tests use the labelled demo extractor |

### Known limitations (0.6.0)
- Latest snapshot only: re-running overwrites the previous assessment; there is no history or audit trail.
- The browser flow (click, refresh, layout) has not been driven in a real browser for this version (see above).
- Attachment evidence is stored only as derived findings; to re-include it the file must be re-sent. A run without the file after a run with it replaces the stronger snapshot with the weaker one (the card shows "Attachment: Not provided").
- Incomplete assessments (message analysis unavailable) are shown but not saved, so such an incident stays "Not assessed" until a complete run succeeds.
- No concurrency control beyond SQLite's: last write wins.
- Risk-summary and list are not paginated in the UI (list capped at 500 as before). The legacy `risk_status` / `analysis` fields remain in the API.
- All 0.5.0 limitations still apply (uncalibrated heuristic weights, synthetic behaviour data, structural attachment analysis, not proof of fraud). App/health version strings still read 0.1.0.

## Feature added in 0.5.0: Risk Correlation Engine (COMPLETED)

First module that combines the independent evidence sources. It consumes the **structured outputs** of message analysis, behaviour analysis and attachment analysis and correlates them with transparent, deterministic rules. **No LLM is asked whether something is a scam**; the only AI in the pipeline is the existing message *extraction*, and the score never depends on a model's opinion. The result explains the *combination* of signals ("the requested financial action is inconsistent with the trusted context"), not "AI thinks this is a scam".

Flow: `Incident -> [Message analysis | Behaviour analysis | Attachment analysis] -> Risk correlation -> Explainable risk assessment`.

### Scoring (HEURISTIC - not probabilities)
Scores are **risk points from correlated indicators** (e.g. "85 risk points"), never "85% chance of fraud". Weights and thresholds are hand-chosen prototype values, not calibrated on real data. Each **category** contributes at most once, at most its weight, however many raw findings map to it (Update.exe + helper.dll is one `executable_content` signal, +25, not +50).

| Category | Signal code | Source | Points | Fires when |
|---|---|---|---|---|
| `urgency` | `HIGH_URGENCY` | message | +10 | `urgency_level == "high"` (medium earns nothing) |
| `secrecy` | `SECRECY_REQUESTED` | message | +10 | `secrecy_indicator` is true |
| `financial_intent` | `FINANCIAL_TRANSFER_INTENT` | message | +10 | intent is `payment_transfer`, `invoice_payment`, `gift_card_purchase`, `bank_detail_change` or `other_financial` |
| `authority_mismatch` | `AUTHORITY_MISMATCH` | message | +15 | only with reliable evidence: the claimed authority AND the recorded role (behaviour profile role, else the submitted sender role) each resolve to exactly one known title (CEO/CFO/COO/CTO/MD/chairperson) and the two differ. Unknown or ambiguous titles never fire. |
| `payment_anomaly` | `AMOUNT_ABOVE_BASELINE` | behaviour | +20 | `amount_anomaly` (profile found) |
| `beneficiary_anomaly` | `NEW_BENEFICIARY` | behaviour | +20 | `new_beneficiary` (profile found) |
| `channel_anomaly` | `UNUSUAL_CHANNEL` | behaviour | +15 | `channel_anomaly` (profile found) |
| `executable_content` | `EXECUTABLE_ATTACHMENT` | attachment | +25 | `contains_executable`, or any `executable_inside_archive` / `executable_file` finding |
| `document_deception` | `DOCUMENT_WITH_EXECUTABLE` | attachment | +20 | `document_with_executable_content` finding |
| `deceptive_filename` | `DOUBLE_EXTENSION` | attachment | +15 | `double_extension` finding |
| `path_traversal` | `PATH_TRAVERSAL` | attachment | +15 | `path_traversal` finding |
| `suspicious_attachment` | `OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING` | attachment | +10 | any other finding rated `high` (counted once) |

Maximum possible raw sum is 185; the **displayed `risk_score` is capped at 100** and the uncapped sum is returned as `raw_points` (with a note when capped). Signal `severity` is derived from points (>=20 high, 10-19 medium, below 10 low) so the two cannot disagree. The behaviour analyzer's own "medium/high" amount severity is *not* used for scoring: any amount above the profile maximum scores a flat +20.

### Thresholds and recommended action (prototype values, not validated)
| Score | Level | Recommended action |
|---|---|---|
| 0-19 | LOW | `PROCEED` |
| 20-39 | MEDIUM | `VERIFY` |
| 40-69 | HIGH | `VERIFY` |
| 70+ | CRITICAL | `HOLD_PAYMENT` |

The engine **only recommends**. It never blocks, holds or executes a payment (`payment_blocked` is always `false`; no payment, banking or messaging code exists in the module).

### "Trust break"
`trust_break_detected` is true when the level is HIGH or CRITICAL **and** at least two independent sources contributed **and** at least one signal says the request does not fit the trusted context (`payment_anomaly`, `beneficiary_anomaly`, `channel_anomaly` or `authority_mismatch`). Then the headline is **TRUST BREAK DETECTED** and the explanation is: "The request is inconsistent with the sender's established behaviour and contains multiple independent indicators of elevated financial-fraud risk." HIGH/CRITICAL without that (e.g. message + attachment only) is reported as "Elevated risk indicators". The text never claims an account was hacked or compromised; the system does not know that.

### Evidence structure (`POST /api/incidents/{id}/analyze-risk` -> `data`)
`risk_score`, `raw_points`, `max_score`, `risk_level`, `recommended_action` (code), `recommended_action_label`, `recommended_action_guidance`, `trust_break_detected`, `headline`, `explanation`, `signals[]`, `category_points{}`, `inputs{message,behaviour,attachment: {status, mode?, detail}}`, `thresholds[]`, `notes[]`, `scoring_method` (`"heuristic_points"`), `disclaimer`, `payment_blocked` (false), `is_final_decision`.
Each signal: `{code, category, source, severity, points, title, message, details[]}` (`details` e.g. the executable file names, bounded to 10).
`inputs[*].status` is `used`, `not_provided`, `not_evaluated` (e.g. no behaviour profile for the sender, or skipped message) or `unavailable` (message analysis failed). Missing evidence adds **no** points and is always shown.

`is_final_decision` is `true` here (unlike the three analyzers, which are `false`): it marks this as the **final output of the analysis pipeline**, per the feature brief. It does **not** mean a payment decision was made or that fraud is proven.

### Integration points
- `backend/app/services/risk_correlation/`: `rules.py` (weights, thresholds, mappings - the single place to tune), `engine.py` (`correlate_risk(message_analysis, behaviour_analysis, attachment_analysis, incident)`, pure, stdlib only, imports none of the analyzers), `service.py` (`assess_incident_risk(incident, attachment_file=None)`: the **only** module that imports the analyzers).
- `routers/incidents.py`: one new endpoint, `POST /api/incidents/{id}/analyze-risk`. Optional multipart field `file`: the incident stores attachment metadata only, so attachment evidence exists only when the file is sent (analyzed in memory, never executed, extracted or stored). Without a file the assessment runs on message + behaviour and says the attachment was "not provided". A bad file returns the same error envelope as `analyze-attachment` (`empty_file`, `file_too_large`, ...). A message-analysis failure (e.g. `TRUSTBREAK_AI_MODE=ai` with no key) does **not** fail the request: message evidence is marked `unavailable` with the reason.
- Computed on demand, **not stored**, no schema change. The stored placeholder `analysis` (`needs_review`) and `services/analysis.py` are intentionally untouched (see decision below).
- Frontend: `components/RiskAssessmentCard.jsx` ("TrustBreak Risk Assessment": score, level, recommended action, "Why this was flagged" evidence cards, recommended-action box, inputs used, notes, disclaimer), `api.analyzeRisk`, inserted on the incident detail page. The attachment file chosen in the Attachment Analysis card is shared with the risk card (`AttachmentAnalysisCard` got an optional `onFileChange` prop).

**Decision - why `analyze_incident` was not changed:** that placeholder runs once at creation, with no file bytes and (in AI mode) would add a network call to every submission; its result is stored. Replacing it would force a schema change and make list/dashboard statuses depend on evidence that does not exist at creation time. The on-demand endpoint matches the other three analyzers. Persisting the assessment is the recommended next step.

### Files added
`backend/app/services/risk_correlation/{__init__,rules,engine,service}.py`, `backend/tests/test_risk_correlation.py` (51 tests), `backend/tests/test_risk_correlation_api.py` (6 tests), `frontend/src/components/RiskAssessmentCard.jsx`.

### Files modified
`backend/app/schemas.py` (risk response models appended), `backend/app/routers/incidents.py` (one endpoint), `frontend/src/api/client.js` (`analyzeRisk`), `frontend/src/pages/IncidentDetail.jsx` (card inserted, shared file state), `frontend/src/components/AttachmentAnalysisCard.jsx` (optional `onFileChange`), `README.md` (endpoint row), and these docs.

### Verification of this feature
| Check | Result |
|---|---|
| Full backend suite (`python -m unittest discover -s tests -t .`, clean venv, FastAPI/httpx installed) | **179 run, 179 passed, 0 skipped** (the original 122 unchanged + 57 new) |
| Risk unit tests: no signals; urgency only; each of beneficiary / amount / channel / attachment alone; multiple signals; CEO demo; missing message / behaviour / attachment; duplicate findings; unknown findings and garbage input; every level boundary (0, 19, 20, 39, 40, 69, 70, 100) incl. real combinations at 35, 40, 55, 70; determinism; AST guards that no analyzer imports another or the risk engine, the pure engine imports no analyzer, and the module has no network / LLM / subprocess / file / payment code | **Passing (51)** |
| HTTP tests (demo with and without file, normal payment, bad file envelope, 404/422/405, nothing stored, existing endpoints unchanged) | **Passing (6)** |
| CEO demo through the real analyzers | **CRITICAL / HOLD_PAYMENT**, trust break detected. With `RBI_Statement.zip`: 130 raw points, displayed 100. Without the file: 85. |
| Normal payment (Arvind Rao, Email, Vendor A, ₹1,00,000, routine message) | **LOW / PROCEED**, 10 points (only `FINANCIAL_TRANSFER_INTENT`) |
| Unknown sender with the demo message | Message evidence only (no profile): 30 points, MEDIUM, **no** trust break |
| `npm run build` | **Passed** (48 modules) |
| Real browser (headless Chrome 131 via Playwright, real uvicorn + Vite): incident page shows the new section; run without file = 85 CRITICAL; choose the zip once in Attachment Analysis, re-run = 100 CRITICAL with Update.exe / helper.dll listed; "TRUST BREAK DETECTED", all evidence cards, "HOLD PAYMENT" and the "not proof of fraud" notice present; the existing Attachment Analysis card still works on the same page; **0 console or page errors** | **Passed** (this one page only; the dashboard, list and create-form flows were not re-driven in a browser) |
| Real Anthropic API | **Not run** (no key). Risk tests use the labelled demo extractor. |

### Known limitations (risk correlation)
- **Scoring is heuristic.** Weights and thresholds are prototype values, not validated or calibrated; the score is **not a probability**. Real-world validation has not been performed and **false positives are expected** (an ordinary invoice payment already scores +10; a legitimate urgent payment to a new vendor scores 50).
- **Synthetic behaviour data only**: two fictional profiles keyed by exact sender name; no real banking data anywhere. Senders without a profile get no behavioural evidence (the form's self-reported "new beneficiary" flag is deliberately ignored, as in 0.3.0).
- **Attachment analysis is structural** (names, signatures, ZIP directory); contents are never read or run. The attachment file must be re-sent for each assessment because only metadata is stored.
- **The risk assessment does not prove fraud**, and no payment is blocked or executed; it is a recommendation for a human.
- **Missing evidence lowers the score.** The same incident is CRITICAL (85) with message evidence and HIGH (55) if message analysis is unavailable; this is shown in `inputs` and `notes`, but a person must read it.
- **Flat weights:** amount is +20 whether 1.05x or 8x the maximum; medium urgency, `credential_or_otp_request` intents and frequency are not scored; the four attachment categories overlap in meaning (an `Invoice.pdf.exe` can score executable + double extension), so an attachment alone can reach 85 points.
- Authority mismatch uses a small English alias list (CEO, CFO, COO, CTO, MD, chairperson); in demo-mode extraction `claimed_authority` is usually null, so the signal rarely fires there.
- Results are not persisted and there is no rate limiting; in AI mode each assessment costs one extraction call.
- The stored placeholder "Recommended action" box and "Needs review" badge still appear on the incident page below the new section; they are the unchanged 0.1.0 placeholder.

## Current architecture

See [ARCHITECTURE.md](ARCHITECTURE.md). In short: `frontend/` (React + Vite + Tailwind) talks only to `backend/` (FastAPI) over REST; the backend owns a single SQLite file in `data/`. The only seam intended for future intelligence is `backend/app/services/analysis.py`.

## Verification status (historical, superseded by the release verification pass above)

_The tables below describe the original build sandbox. The HTTP layer, `npm run build` and the full test suite have since been run; see "Release verification pass (v0.4.0)"._

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

**Update:** the application start-up, HTTP routes and production build have now been verified (see the release verification pass above); only real-browser checks remain open.

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

**Step 0 - DONE (see "Release verification pass (v0.4.0)"):** (original text)  follow the README run steps, then run `python -m unittest discover -s tests -t . -v` after `pip install -r requirements-dev.txt` (all tests should run, none skipped), and `npm run build` in `frontend/`. Fix anything that fails before adding features. Update the table above with the results.

**Step 1 - DONE in 0.5.0: the risk correlation engine** (see "Feature added in 0.5.0"). It combines `analyze_message` extraction, `analyze_behaviour` signals and attachment analysis into an explainable, deterministic risk level and recommended action. The older trusted-profile / `trusted_profiles` table idea (original text of this step) is superseded by the behaviour baseline.

**Step 2 - DONE in 0.6.0: persist the risk assessment with the incident and make it the incident's real status.** Store the assessment (score, level, action, signals, inputs, timestamp) when it is run, retire the placeholder `needs_review` status and the fixed placeholder recommended-action on the list, dashboard and detail pages in favour of the stored level, and show which analyses were run. This needs a deliberate schema change (a stored analysis snapshot or table) and is the prerequisite for the case workflow (ROADMAP step 4). See [ROADMAP.md](ROADMAP.md).

**Step 3 - the single next recommended feature (after 0.6.0): case workflow.** Let a human act on the stored recommendation: an incident status (open / verified / rejected), a required reason or analyst note, and an audit trail of who decided what and when, kept separate from the machine-generated assessment. Prerequisite (a persisted assessment) is now met. See [ROADMAP.md](ROADMAP.md) step 4.

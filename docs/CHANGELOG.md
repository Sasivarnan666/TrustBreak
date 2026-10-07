# Changelog

## 0.13.0 (minor) - 2026-10-07 - Counterfactuals, scenarios, verification, timeline, command center, report

The Risk Engine, weights and thresholds are **unchanged**; this release extends the existing architecture. The CEO scenario still reaches CRITICAL / HOLD_PAYMENT / TRUST BREAK DETECTED (100, 130 raw points with the zip) and the benign payment is LOW / PROCEED (8).

### Added
- **Counterfactual analysis** (`services/counterfactual.py`, `GET /api/incidents/{id}/counterfactuals`): rebuilds the normalized signals of the latest stored assessment, removes one evidence group at a time and re-runs `correlate_signals`. Read-only; nothing persisted. Reports before/after score, raw points, level, action, affected signals and a computed explanation, the largest reduction and the smallest combination that lowers the level. When the score is capped at 100 a single change can lower raw points without lowering the score; this is shown honestly. Assessments from an older engine that cannot be reproduced exactly are reported as unavailable.
- **Scenario simulator** (`services/scenarios.py`, `GET /api/scenarios`, `POST /api/scenarios/{id}/load`): 7 synthetic scenarios (inputs only). Loading creates a normal incident (`incidents.scenario_id`, API `is_synthetic`) and runs the real pipeline with an in-memory harmless ZIP where relevant. No score or level is stored in the scenario definitions.
- **Independent verification** (`services/verification.py`, table `verification_events`, `GET/POST /api/incidents/{id}/verification`): states NOT_STARTED / IN_PROGRESS / CONFIRMED / FAILED, append-only (UPDATE blocked by trigger), applicable when the latest assessment recommends VERIFY or HOLD_PAYMENT. Recommended methods never include the channel the request arrived on. Separate from risk assessments and from the final case decision.
- **Forensic timeline** (`services/timeline.py`, `GET /api/incidents/{id}/timeline`): derived only from persisted rows; analyzer events carry the timestamp of the assessment run that recorded them; no timestamp is invented.
- **Command-center dashboard** (`services/dashboard.py`, `GET /api/dashboard`): KPIs, risk distribution, trust-break categories, active high-risk incidents, recent critical incidents, system status. AI status is derived from configuration and the last persisted extraction state; fallback is labelled "AI unavailable - deterministic fallback active".
- **Printable incident report** (`services/report.py`, `GET /api/incidents/{id}/report`): self-contained, HTML-escaped, 14 sections, browser print / Save as PDF. No secrets, no scripts beyond the print button.
- **Frontend**: top navigation (Dashboard, Incidents, Scenarios, Identities), analyst workspace for incident detail (header, trust-break summary, evidence chain, risk breakdown, counterfactuals, message and attachment intelligence, verification, timeline, history, decision, export), new dashboard, Scenarios and Identities pages.

### Schema
- `incidents.scenario_id TEXT` (idempotent migration). New table `verification_events` (+ index and immutability trigger). No existing table was altered otherwise.

### Verification
- Backend: see PROJECT_STATE for the exact run. Frontend: `npm run build` passed. The UI was not driven in a browser in this environment.

## 0.12.0 (minor) - 2026-10-07 - Risk Engine 2.0 + signal provenance

**Scoring changed on purpose.** The old 0.6.0 weights are replaced by a documented Risk Engine 2.0 table (`engine_version` is now `2.0.0`, `scoring_method` `heuristic_points_v2`). Weights are prototype heuristics, not statistically calibrated, and the score is not a probability of fraud. Still one engine: the existing deterministic correlation engine was extended, not duplicated. AI still only extracts evidence; it never scores, grades or recommends.

### Added
- `services/risk_correlation/signals.py`: the normalized `RiskSignal` (code, category, source, title, message, why, evidence, confidence, points, severity, group, analyzer, base_points, capped, related_signal_codes, corroborating_sources).
- `services/risk_correlation/adapters.py`: one adapter per evidence source (message extraction, 11 social-engineering indicators, 8 behaviour anomalies, attachment findings) -> normalized signals. Adapters hold no scoring numbers.
- Seven categories: IDENTITY, COMMUNICATION, FINANCIAL, BENEFICIARY, BEHAVIOUR, SOCIAL_ENGINEERING, ATTACHMENT. Missing evidence adds nothing.
- Sources describe where the evidence really came from: `rule`, `synthetic_baseline`, `AI` (grounded model item), `fallback` (deterministic rules because the AI provider failed), `attachment_static`, `system`. No threat intelligence is claimed.
- `correlate_signals(signals, inputs)`: the single scoring path over normalized signals. `correlate_risk(...)` = `collect_signals(...)` + `correlate_signals(...)`. A later phase can score "the same incident with signal X removed" through this exact function (not built yet; one seam test only).
- UI: Risk Assessment card groups evidence by category and shows, per signal, title, points, severity, source, why it matters, evidence, confidence, "counted once" related signals and cap notes; "Prototype heuristic risk score" / "Score is not a probability of fraud" wording and a new disclaimer. Pre-2.0 assessments render under an "earlier engine version" group.
- Tests: `tests/test_risk_engine_v2.py` (57 tests): normalized model, category mapping, provenance, scoring table, deduplication, caps, the 12 regression scenarios, counterfactual seam, persistence, engine version, immutable history, pre-2.0 readability, human/engine separation, stale-decision protection.

### Changed (intentional behaviour change)
- Deduplication, by explicit rules in `rules.py` (`CONSOLIDATION_GROUPS`): one contribution per group (time pressure: urgency / high urgency / deadline; concealment: secrecy / isolation; payment request: transfer intent / payment pressure; authority: claim / mismatch; channel: unusual / rare; attachment executable: executable / risky extension; attachment disguise: document-looking / double extension; attachment structure). The strongest signal is scored; the rest are listed as `related_signal_codes`.
- Category caps (BEHAVIOUR 20, SOCIAL_ENGINEERING 30, ATTACHMENT 40) so many weak related indicators cannot outweigh context-inconsistency evidence. Social-engineering weights scale with confidence (high 1.0, medium 0.75, low 0.5).
- The previously open question is resolved: `Invoice.pdf.exe` no longer scores 25 + 20 + 15; it scores executable 25 + one disguise contribution 12.
- Behaviour signals from 0.10.0 (time, day, frequency, velocity, channel distribution) and social-engineering signals from 0.11.0 are now scored (small weights, capped). `NOT_ENOUGH_BASELINE_DATA` still produces no history-based anomaly.
- Demo (real pipeline, no hard-coded score): with `RBI_Statement.zip` 130 raw points, displayed 100 (capped), CRITICAL / HOLD_PAYMENT / TRUST BREAK DETECTED; without the zip 93, CRITICAL. Benign payment (Arvind Rao, Email, Vendor A, INR 1,00,000, routine wording): 8, LOW / PROCEED. Previous values: 100 (130 raw) / 85 / 10.
- `ASSESSMENT_VERSION` now follows `rules.ENGINE_VERSION`; each history row stores the engine version of the run that wrote it. The persistence guard checks one signal per group, no repeated code and category caps for 2.0 results, and still accepts pre-2.0 rows.
- API: signals gain optional fields (`why`, `evidence`, `confidence`, `group`, `analyzer`, `base_points`, `capped`, `related_signal_codes`, `corroborating_sources`); `source` takes the new values and still accepts the old ones; result gains `engine_version`. Endpoints are unchanged. The evidence graph reads `analyzer` (falls back to the old `source`).
- Existing tests updated only where scores or fields intentionally changed (weights, demo score, source -> analyzer, one-signal-per-group invariant). None deleted.

### Known limitations
- Weights, caps and thresholds are uncalibrated prototype values. Time / day / velocity / frequency still need an explicit `received_at` (API only). English-only social-engineering rules. Attachment analysis is structural only. Live Gemini still not exercised. No browser-driven UI test.

## 0.11.0 (minor) - 2026-10-05 - P1.5 Social-engineering signal analysis

**Scoring is unchanged** (engine, weights, thresholds, `engine_version`). The risk engine ignores the new block; the demo still scores 100 CRITICAL with the zip, 85 without.

### Added
- `services/message_analysis/social_engineering.py` (stdlib only): 11 signals - authority, urgency, secrecy, verification suppression, isolation, fear/threat, deadline, payment, credential pressure, impersonation cue, unusual instruction. Every signal: `detected`, `evidence` (the sentence containing the match, <= 200 chars), `matched_phrase`, `source` (`AI` | `rule` | `fallback`), `sources` (all origins), `confidence` (low / medium / high).
- Deterministic detection on normalized text (NFKC, curly quotes, zero-width characters, whitespace/case) with patterns rather than exact strings; covers every phrase listed in the brief. Negation guard: "do not share your OTP" and "this is not confidential" are not requests.
- AI boundary: the model reply may carry an OPTIONAL `social_engineering_signals` list of `{signal, evidence, confidence}`. It is validated separately and never fails the extraction: unknown signal, extra key (e.g. `risk_score`), bad confidence, duplicate, or evidence that is not found in the message => that item is dropped and reported in `notes`. The 12-field extraction contract and `validate_extraction` are unchanged; any top-level risk field is still rejected. The model is never asked for score, level, action or case decision.
- Origin labels: `AI` (validated model item), `rule` (fixed patterns; also run beside the AI), `fallback` (the same patterns because an AI provider was wanted but failed; no semantic understanding claimed). Demo mode (offline on purpose) is labelled `rule`.
- API: `social_engineering` on the analyze-message response (additive); `None` for an empty message.
- UI: "Social engineering indicators" panel inside Message Analysis; each detected signal shows its confidence and expands to the exact evidence and origin; undetected signals listed separately; states "evidence only, not a score".
- 22 new tests (504 total).

### Changed
- Gemini request schema is now `response_json_schema()` (extraction schema + optional signal list); `extraction_json_schema()` is untouched. One existing test updated to compare with the new function.

### Known limitations
- English-only patterns. Not scored: urgency / secrecy / deadline / authority overlap with existing risk categories (`urgency`, `secrecy`, `authority_mismatch`); the Risk Engine 2.0 phase must consolidate them so one piece of evidence is never counted twice (e.g. `secrecy_indicator` and `secrecy_pressure`, urgency and deadline). Live Gemini was not called, so the AI path is verified with fake clients only.

## 0.10.0 (minor) - 2026-10-05 - P1.4 Behaviour baseline 2.0

**Scoring is unchanged** (engine, weights, thresholds and `engine_version` untouched). The risk engine still reads only the three original behaviour flags; the new signals are evidence only until the Risk Engine 2.0 phase. The demo still scores 100 CRITICAL with the zip, 85 without.

### Added
- `services/behaviour/activity.py`: deterministic SYNTHETIC history per trusted identity (CEO-001: 87 events, CFO-001: 64), generated from the identity registry (channels, beneficiaries, amount range, working hours) with a fixed-seed integer generator: no `random`, no clock, identical every run. Fields: activity_id, identity_id, timestamp, channel, amount, currency, beneficiary, action, status.
- `services/behaviour/baseline.py`: descriptive metrics on completed events (min / max / mean / median / p25-p99 nearest-rank, weekly frequency, maximum 10-minute burst, channel and beneficiary distributions, hour and weekday distributions). Labelled "Synthetic behavioural baseline"; no statistical-significance claim.
- `services/behaviour/workhours.py`: parser for the stored `typical_working_hours` (e.g. `09:00-19:00 IST, Mon-Sat`); timestamps are converted to IST; unparseable -> not evaluated.
- New behaviour signals (all `source: synthetic_baseline`, each with structured `evidence`): `CHANNEL_DISTRIBUTION_ANOMALY` (known channel below 10% of history; a channel absent from history stays `UNUSUAL_CHANNEL`, never both), `UNUSUAL_TIME`, `UNUSUAL_DAY`, `FREQUENCY_ANOMALY` (requests in 7 days above the historical weekly max), `VELOCITY_ANOMALY` (>= 3 requests in 10 minutes and above the historical burst). The existing amount signal keeps its code `AMOUNT_ABOVE_BASELINE`.
- Amount evidence: `ratio_to_typical_max` (18,50,000 vs 2,00,000 = 9.25x; the legacy `amount_deviation` 8.25 is unchanged) and a historical percentile label that never overclaims (">99th percentile" only with >= 100 events; with fewer it says "Above every one of the N historical events").
- `NOT_ENOUGH_BASELINE_DATA` (< 20 completed events or < 28 days) for channel distribution, frequency and velocity; no anomaly is invented. Response gains `baseline` and `baseline_status`; anomalies gain `source` and `evidence` (additive).
- Optional `received_at` (ISO-8601) on incident create, stored in a new nullable column (added by `_migrate`). Time, day, frequency and velocity use ONLY this value and earlier incidents of the same identity that also have it; the wall-clock `created_at` (when a record was typed in) is deliberately not used, so ordinary demo runs never produce time-of-day anomalies. Unknown time -> "not evaluated". Invalid value -> 422; naive values are treated as UTC.
- UI: Behaviour card rebuilt as BEHAVIOURAL BASELINE (typical vs current amount with multiple, normal vs current channel with historical distribution bars, known vs current beneficiary, working hours, history size) plus DETECTED DEVIATIONS with expandable evidence.
- 32 new tests (482 total), including the CEO-001 acceptance case derived from the engine and an API test where velocity emerges from three stored incidents.

### Changed
- One existing test updated on purpose: a profile with no history now reports frequency as `NOT_ENOUGH_BASELINE_DATA` instead of `not_evaluated` (`test_frequency_without_baseline_is_not_enough_baseline_data`).

### Known limitations
- Behaviour history is generated demo data, never real. No form field for `received_at` yet (API only); the Phase 6 scenario simulator is the intended producer. Velocity/frequency count only incidents that carry `received_at`. The risk engine does not score the new signals yet.

## 0.9.0 (minor) - 2026-10-05 - P1.2 Trusted identity model and P1.3 evidence graph

**Scoring is unchanged** (engine, weights, thresholds, `engine_version` stays `0.6.0`). The demo still scores 100 CRITICAL with the zip, 85 without.

### Added
- `services/identity/` (stdlib only): `TrustedIdentity` (identity_id, employee_id, display_name, role, department, organization, corporate_email, phone_reference, aliases, normal / trusted / restricted channels, known_beneficiaries, typical amount min / max, working hours, profile_version, created_at, updated_at, active) and a synthetic registry (`CEO-001` Arvind Rao, `CFO-001` Meera Iyer). The behaviour profile registry is now derived from it (single source of truth). CEO typical minimum is now explicit INR 20,000.
- `incidents.sender_identity_id` / `sender_identity_source` (`explicit` | `name_match` | `none`), added in place by `_migrate`; `IncidentCreate.sender_identity_id` is optional and an unknown id is `422` (never guessed). `sender_name` is kept for display and compatibility. Rows created before 0.9.0 have no id and resolve by exact name at read time.
- Resolution rules: explicit id first; exact name or alias only as a fallback when no id is given; an id that does not exist never falls back to the name; role and substring matching are never used. Behaviour analysis (`analyze_incident_behaviour(..., sender_identity_id=)`) prefers the id.
- `GET /api/identities`, `GET /api/identities/{identity_id}` (identity, baseline summary, activity summary from stored incidents). Read-only. No separate activity endpoint.
- `services/evidence_graph.py` (pure, deterministic) and `GET /api/incidents/{id}/trust-graph`: nodes / edges plus EXPECTED-vs-OBSERVED rows for channel, beneficiary and amount (e.g. 9.25x the typical maximum). It reads the identity baseline, behaviour checks and the latest STORED assessment's signals; the verdict node only repeats the stored assessment. Nothing is scored, written or sent to an AI. Without an assessment the verdict is "Not assessed"; with no linked identity no baseline is invented.
- UI: "Trusted Identity" card (profile, then Current event with Expected vs Observed cells) and "Evidence Graph" card (SVG, no new dependency, text outline for accessibility, refetched when the assessment changes). Create form: optional trusted-identity selector; the demo scenario sets `CEO-001`.
- 30 new tests (450 total).

### Known limitations
- Only executable entry names are persisted in assessment signals, so the graph shows `Update.exe` and `helper.dll` but not `Statement.pdf`. The attachment node says "not analyzed" when the file was not part of the latest assessment.
- Identities are code-resident synthetic data (no management UI, no DB table); `typical_working_hours`, `restricted_channels` and `trusted_channels` are stored and shown but not yet compared. No authentication.
- Behaviour baseline 2.0 and social-engineering signal analysis were NOT started in this version.
- Not driven in a real browser; rendering was checked with a server-side render of real API output and `npm run build`.

## 0.8.0 (minor) - 2026-10-04 - P1.1 Immutable assessment history and decision linkage

**Scoring is unchanged** (engine, weights, thresholds, `engine_version` stays `0.6.0`).

### Added
- `risk_assessment_history` (append-only; UPDATE blocked by trigger; `UNIQUE (incident_id, version_number)`), view `latest_risk_assessments`. Every `POST /analyze-risk` that is saved appends a new version; nothing is overwritten. This also fixes the P0.2 finding where a re-run without the attachment replaced the stronger assessment: v1 keeps its attachment evidence.
- `GET /api/incidents/{id}/assessments` (summaries, oldest first) and `GET /api/incidents/{id}/assessments/{version}` (full stored evidence). Incident detail carries `assessment_history`; assessments expose `assessment_id`, `version_number`, `engine_version`, `is_latest` (`assessment_version` kept as the legacy alias of `engine_version`).
- `case_actions.assessment_id`: a decision records the exact assessment it was based on and the API returns `assessment_number`, `assessment_risk_score`, `assessment_risk_level` from the immutable row. `POST /decision` accepts optional `assessment_id`; if a newer assessment exists it answers `409 assessment_superseded` and writes nothing; a foreign id is `422 assessment_not_found`. A decision with no assessment is still allowed and recorded as unlinked.
- In-place upgrade (`database._migrate`): adds the column and backfills each old snapshot as version 1; idempotent. Existing decisions stay unlinked (they were not linked when recorded).
- UI: Assessment history card (v1 -> score level timeline, current marker, "decision based on this version" marker, click to load read-only stored evidence); assessment header now shows "Assessment vN"; case form says which assessment a decision will be recorded against; audit trail shows "Decision based on Assessment v3 (100/100 CRITICAL)".

### Changed
- `risk_assessments` is legacy (read-only, backfill source). The list join, dashboard counts and incident status read the latest history row.
- Case workflow now reads the *identity* of the latest assessment (never its scoring data). Tests that asserted "one snapshot row" were updated to the history semantics (assert both versions exist); the "decision leaves the assessment byte-for-byte unchanged" tests now compare the whole history.

### Tests
- New `tests/test_assessment_history.py` (20): numbering, per-incident numbering, exact retrieval of old versions, immutability trigger, list/summary use latest once, 8-way concurrent runs, decision linkage, stale / foreign / unknown ids, unlinked decisions, history untouched by decisions, in-place upgrade from a 0.7.x-shaped database (twice, idempotent), the API demo flow v1 -> v3 with the decision on v3, unsaved results, 404s. Mutation-checked: breaking the linkage or the version counter fails the suite.

### Not done / limits
- Each run creates a version even if nothing changed (per the brief); no de-duplication or diff view yet. Earlier decisions made before 0.8.0 cannot be linked retroactively. Frontend verified by build only.

## 0.7.7 (patch) - 2026-10-04 - P0.4 Test integrity

Method: fresh virtualenv from `requirements-dev.txt`, `python -W error::ResourceWarning`, branch coverage (coverage.py), an AST scan for tests without assertions, a scan for skipped tests, clean `npm` build.

### Found and fixed
- **Bug:** the legacy Anthropic provider classified a socket timeout as `unreachable`. It now reports `timeout` (`TimeoutError`, or a `URLError` whose reason is a timeout), consistent with Gemini.
- **Weak test:** `test_real_engine_output_passes` had no assertion; it now asserts the guard returns `None`.
- **Coverage gaps** (before: 96% of `app/`, Anthropic provider 42%, the failure-kind code added in 0.7.4 untested on the Anthropic path): now 98%.

### Added (`tests/test_regression_p04.py`, 25 tests; assertions in existing tests untouched)
- Anthropic provider over a mocked transport: success, key only in the header, 429 / 401 / 403 / 404 / 5xx / 400 mapping with no body or key leakage, both timeout shapes, network failure, oversized and malformed replies, auto-fallback and `ai`-mode error, and a valid end-to-end reply.
- Gemini edges: `.text` raising, SDK package missing, a `ProviderError` raised inside the client keeps its kind.
- Extraction validation rejections (non-object, wrong types, control characters, NaN / inf, bool as number, fractional / zero amounts, entity limits).
- Attachment signatures (ELF, PNG, JPEG, GIF, OLE, RAR, 7z, gzip, unknown), unsupported archives reported not opened, shortcut files, declared-size warning.
- Behaviour with a profile that has no history, consistency-guard edge cases, incident deleted mid-request (404), size formatting.

### Not covered / honest limits
- Coverage is a measurement, not a CI gate. Remaining misses are mostly defensive branches (`case_workflow` concurrent rollback, config parsing, mock-extractor numeric edge cases).
- No frontend unit or browser tests exist; the UI is verified by `npm run build` only.
- Nothing has run against the live Gemini API.

## 0.7.6 (patch) - 2026-10-04 - P0.3 Documentation drift

No behaviour change beyond the version string. 
- **Version:** single source `backend/app/__init__.py` (`__version__`); `/api/health` and the FastAPI app now report it (they said `0.1.0`); `frontend/package.json` and lockfile aligned.
- **README:** status banner updated, new Feature status table (implemented / partial / planned / experimental / not implemented), `analyze-attachment` added to the API table, fallback wording and failure kinds documented, error codes completed.
- **ROADMAP:** P0-P4 phase plan with DONE / NEXT / LATER; the original sequence is kept as history; 7c no longer claims to be "next".
- **ARCHITECTURE:** `analysis_state` / `failure_kind`, the pre-persistence consistency guard and the `inputs.message` provenance are described.
- **PROJECT_STATE:** authoritative Summary block (version, completed features, architecture, limitations, known bugs, test count, next priority, demo readiness, environment); older sections are history.
- **.env.example:** removed the obsolete "export the file" instruction (the backend loads `backend/.env` since 0.7.3).
- **Tests:** new `tests/test_docs_sync.py` fails when the version or the claimed test count drifts between code and docs.

## 0.7.5 (patch) - 2026-10-04 - P0.2 Assessment correctness audit

Audit of message + behaviour + attachment -> correlation -> persistence -> API -> UI. **Weights, thresholds, levels, actions and signal rules are unchanged.**

### Audit findings
- **Verified OK:** the score is computed only by `correlate_risk`; the API accepts no score input; extraction output carrying `risk_score`/`risk_level` is ignored (and rejected by extraction validation); the frontend only renders backend values (its single `Math.min` clamps a progress-bar width); one signal per category, so repeated findings / duplicate file names do not add points; repeated runs are idempotent; detail, list, summary and a restarted server agree.
- **Gap fixed:** nothing checked that a result was self-consistent before it was stored. Added `risk_repository.check_result_consistent` (score = min(cap, sum of signal points), raw = sum, category_points = signals, level matches thresholds, action matches level, no duplicate category), called by `POST /analyze-risk` before saving. A contradicting result is refused and nothing is written. `save_risk_assessment` itself stays a plain store.
- **Open, deliberately not changed here:** (1) a re-run without the file replaces an assessment that had attachment evidence with a lower one (the card shows "Attachment: Not provided"); fixed structurally by P1 assessment history. (2) One deceptive `Invoice.pdf.exe` fires three related attachment categories (25 + 20 + 15). The 25 + 20 pair matches the brief's attachment example; merging related signals is a scoring decision for P1 Risk Engine 2.0. Both are pinned by characterization tests. (3) `ASSESSMENT_VERSION` is still `"0.6.0"` although `inputs.message` gained provenance keys in 0.7.4; P1 introduces `engine_version` per assessment.

### Tests
- New `tests/test_assessment_integrity.py` (15): invariants across critical / no-file / benign / unknown-sender / double-extension cases, duplicate-finding handling, determinism, smuggled-score rejection, 7 tamper cases for the guard, stored = returned = listed = summarised, client cannot supply a score, idempotent re-runs, re-run-without-file characterization, refused-not-persisted, frontend scan. 369 total, all passing.

## 0.7.4 (patch) - 2026-10-04 - P0.1 Gemini resilience: classified failures, explicit states, fallback disclosed in risk inputs

Context: the free-tier Gemini project returns HTTP 429 (`RESOURCE_EXHAUSTED`). This is a quota condition, not a bug. The existing fallback extractor already handled it; this patch makes every AI failure **classified, labelled and visible**. No new fallback system was added. **Risk engine weights, thresholds, levels and recommended actions are unchanged.**

### Changed
- `providers/base.py`: `ProviderError.kind` and `FAILURE_KINDS` (`quota_exhausted`, `auth_error`, `model_not_found`, `timeout`, `service_unavailable`, `unreachable`, `http_error`, `empty_response`, `invalid_response`, `not_configured`, `sdk_missing`, `unexpected`); `kind_for_status()`. Gemini and Anthropic providers classify HTTP status, timeout, network, empty/blocked and shape failures. Error text still carries a status code only.
- `service.py`: result gains `analysis_state` (`ai` | `fallback` | `mock` | `skipped`) and `failure_kind`; a per-kind hint is added to `fallback_reason` (no provider text, no secrets); any unexpected exception from a provider now degrades to a labelled fallback in `auto` (and `ai_unavailable` in `ai` mode) instead of escaping. `ExtractionError.failure_kind` is returned in the error envelope `details` as `[{"failure_kind": ...}]`.
- Risk engine: `inputs.message` now also reports `analysis_state`, `provider`, `failure_kind` and an honest `detail` ("Deterministic fallback extraction used ... not AI output"). Display/provenance only; no scoring path reads these fields.
- UI: message card shows "Gemini unavailable - deterministic fallback used" (plus the failure label), the distinct "Demo mode" and "AI analysis - Gemini" states, and an "AI analysis unavailable" error block in `ai` mode. Risk card marks the message input "fallback, not AI" (amber) or "AI-extracted".

### Tests
- New `tests/test_ai_resilience.py` (16): 13-row failure table (429, 401, 403, 404, 500, 503, 400, timeout, network, empty/blocked, non-JSON, schema violation, injected verdict field) in both `auto` and `ai` modes; missing key; missing SDK; unexpected provider bug; four distinct states; derived state; score parity with fallback vs AI; fallback disclosure persisted with the assessment; no secret in any response. 354 total, all passing.

### Not done / unverified
- No live Gemini call (no key in the authoring environment). A real 429 was exercised through fakes only.
- Frontend verified by `npm run build` only, not in a browser.
- `analysis_state: "unavailable"` is intentionally not a success value: it appears as the `ai`-mode error and as the risk input status `unavailable`.

## 0.7.3 (patch) - 2026-10-03 - Backend loads backend/.env automatically

Reported: the UI said "No AI API key is configured (GEMINI_API_KEY is not set)" although `backend/.env` held the key. **Root cause:** nothing in the backend ever read `.env`; the key only reached the app if it was exported into the shell first, and `python-dotenv` was not installed. Gemini adapter, provider/model behaviour, extraction, behaviour, attachment and risk code are untouched.

### Changed
- `app/config.py`: `ENV_FILE` (anchored to `backend/.env`, independent of the working directory) and `load_env_file()`. Variables already set (non-empty) in the real environment win; blank ones are filled from the file; a missing file is fine; `TRUSTBREAK_LOAD_DOTENV=0` disables loading. Values are never logged or returned.
- `app/main.py`: calls `config.load_env_file()` at import, before configuration is read.
- `requirements.txt`: added `python-dotenv>=1.0,<2.0`.
- `tests/__init__.py`: sets `TRUSTBREAK_LOAD_DOTENV=0` so a developer's real `.env` never reaches the suite.

### Tests
- 9 new tests in `tests/test_env_loading.py` using a placeholder value only (precedence, blank fill, missing file, disable switch, any-cwd loading, `.env` git-ignored, example key empty). 338 total.

## 0.7.2 (patch) - 2026-10-03 - Behaviour profile lookup investigation (no code change)

Reported: TB-0003 showed "No behaviour profile exists for this sender". **Root cause: data, not code.** The stored `sender_name` of TB-0003 is `Jason` (hex `4A61736F6E`, role "Chief Executive Officer"), not `Arvind Rao`; the synthetic registry has no profile for Jason, so "no profile" is the correct, designed result. The seeded demo sender and the form's "Load demo scenario" both send exactly `Arvind Rao` and match `CEO-001` (verified end to end through the repository: `AMOUNT_ABOVE_BASELINE`, `NEW_BENEFICIARY`, `UNUSUAL_CHANNEL`).

### Decision
`get_profile_for_sender` was **not changed**. It already matches exact name or alias after casefold + whitespace collapse (leading/trailing, repeated, tabs, NBSP). Matching on role ("CEO") or loosening to substrings would let any CEO-titled stranger inherit another person's baseline, which is unsafe. Incidents have no sender-ID field, so ID-preferred matching is not possible without a schema change (out of scope).

### Tests
- 6 regression tests (`ProfileLookupRegressionTests`): exact, case-insensitive, surrounding whitespace, repeated/NBSP whitespace, unknown senders (incl. `Jason`, partial names, `Mr. Arvind Rao`, `CEO-001`, role text) stay unmatched, role is ignored.

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

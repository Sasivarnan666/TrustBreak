# Architecture

## Overview

```
 Browser (React SPA, :5173)
        │  fetch("/api/...")            Vite dev server proxies /api
        ▼
 FastAPI app (:8000)
   routers/incidents.py   HTTP only: parse, call repository, wrap in envelope
   schemas.py             Pydantic: request validation + response shapes
   repository.py          SQL (stdlib sqlite3), incident row <-> model mapping (joins the latest assessment)
   risk_repository.py     SQL for persisted risk assessments (save / latest / summary)
   case_repository.py     SQL for the case_actions audit trail (append / latest status / history / counts)
   services/case_workflow.py  human case workflow: transition rules + record_decision (no risk logic)
   services/analysis.py   PLACEHOLDER analysis (replaceable seam)
   services/message_analysis/  message -> validated structured JSON (AI or labelled demo mock)
   services/behaviour/    synthetic profile + deterministic anomaly signals (no scoring)
   services/attachment_analysis/  safe static file inspection (no scoring)
   services/risk_correlation/  combines the three analyzers' outputs -> explainable risk assessment
   errors.py + main.py    one JSON envelope for success and every failure
        │
        ▼
 SQLite file  data/trustbreak.db   (`incidents` + `risk_assessments` + `case_actions`)
```

Frontend and backend share nothing except the REST contract below.

## Backend modules (`backend/app/`)

| Module | Responsibility | Does NOT |
|---|---|---|
| `main.py` | App factory, lifespan (create DB, seed demo), CORS, error handlers, `/api/health` | contain business logic |
| `routers/incidents.py` | The incident endpoints (CRUD plus on-demand message, behaviour, attachment and risk analysis) | touch SQL directly |
| `schemas.py` | Validation rules and response models | know about the database |
| `repository.py` | Create / get / list / count incidents; attaches the latest assessment (one LEFT JOIN on the list) | validate input or decide risk |
| `risk_repository.py` | Save (upsert) / get latest / summarise persisted risk assessments | compute scores or import the analyzers |
| `case_repository.py` | SQL for `case_actions`: append audit row, current status, history, counts, backfill | know about risk scoring or validate transitions |
| `services/case_workflow.py` | Transition table, `record_decision` (transactional), history/state/summary builders | read or write risk assessments, or touch payments |
| `services/analysis.py` | `analyze_incident(payload) -> Analysis` | persist anything |
| `database.py` | Connections, schema, `get_db` dependency | |
| `seed.py` | Synthetic demo incident | |
| `config.py` | Env-var settings, read at call time | |
| `errors.py` | `AppError`, `error_body()` | |

### Message analysis service (`services/message_analysis/`)

```
Message (untrusted)
   |
   v
AI provider adapter  (providers/: Gemini | Anthropic legacy | Mock)
   |   LLM providers: prompt.py -> complete(system, user) -> parse_model_reply -> validate_extraction (strict)
   |   Mock provider: mock_extractor.py (regex rules, NOT AI) -> same validate_extraction
   v
Structured MessageExtraction  (12 fixed fields, unchanged)
   |
   v   (consumed by the risk assessment orchestration, never raw LLM output)
Behaviour analysis  +  Attachment analysis  ->  deterministic Risk Correlation  ->  Risk assessment
```

`analyze_message()` returns `MessageAnalysis { mode, model, extraction, notes, fallback_reason, provider, requested_provider, is_fallback, is_final_decision=false }`. `mode` is `ai` / `mock` / `skipped`; `provider` is who produced the extraction; `is_fallback` is true only when an AI provider was wanted but the deterministic extractor ran. Since 0.7.4 the result also has `analysis_state` (`ai` / `fallback` / `mock` / `skipped`) and `failure_kind` (why the AI path failed: quota 429, auth, model, timeout, 5xx, network, empty, invalid, no key, SDK missing, unexpected). A provider failure is a `ProviderError` with a `kind`; any other provider exception also degrades to a labelled fallback in `auto`. In `ai` mode `ExtractionError` carries the kind into the error envelope `details`.

| Module | Responsibility |
|---|---|
| `schema.py` | Dataclasses, `validate_extraction` (exact keys, enums, types, ranges; authoritative), `extraction_json_schema()` (derived from the same constants, sent to Gemini as the structured-output request). Stdlib only. |
| `prompt.py` | System prompt (message = untrusted data) and per-request random-delimiter wrapping |
| `providers/base.py` | `MessageProvider` contract `analyze_message(text) -> MessageExtraction`, `LLMProvider` (prompt + parse + validate, once, for every LLM backend), `ProviderError` |
| `providers/gemini.py` | Official `google-genai` SDK, one text-only `generate_content` call, JSON mime type + response schema, no tools; errors carry a status code only |
| `providers/anthropic.py` | Legacy Anthropic Messages API (stdlib urllib); kept, not required |
| `providers/mock.py` | Offline demo provider wrapping `mock_extractor.py` |
| `providers/__init__.py` | `build_provider(name, key, model, timeout)` |
| `ai_provider.py` | Backward-compatible re-exports (`AnthropicClient`, `ProviderError`) |
| `service.py` | Provider selection result, fallback policy (`auto`/`ai`/`mock`), provenance labels, `ExtractionError` |

Configuration (`app/config.py`) is the only place that reads the environment or names a default model. Provider precedence: `TRUSTBREAK_AI_MODE=mock` > `TRUSTBREAK_AI_PROVIDER` > `GEMINI_API_KEY` > lone `ANTHROPIC_API_KEY` (legacy) > `gemini`.

Rules: nothing outside this package imports a provider or the prompt (AST-tested for the risk, behaviour and attachment packages); the router and the risk assessment call only `analyze_message`; the risk engine reads `MessageAnalysis.extraction` and has no LLM dependency and never sees raw model text. The core is stdlib-only apart from the lazily imported `google-genai`; the pydantic models in `schemas.py` (`MessageAnalysisOut`...) only shape the HTTP response. `POST /api/incidents/{id}/analyze-message` is computed on demand and not stored.

**Security boundaries of the provider call.** The message is untrusted data (random delimiters, never in the system prompt). The Gemini request is text only: no tools/function calling, no URL context, no search grounding, no code execution, no files or attachment bytes. Replies are validated; unknown keys (an injected `risk_level`) are rejected. The API key is read from the environment on the backend, travels only in the SDK's auth header, and is never logged, returned or put in an error message. The model cannot change status, scores or case state: it has no access to them. **Gemini does not determine the final risk score** - the deterministic risk engine does.

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

### Risk correlation engine - Risk Engine 2.0 (`services/risk_correlation/`)

```
Message Analysis (extraction + 11 social-engineering indicators) ─┐
Behaviour Analysis (synthetic baseline anomalies) ────────────────┼─ adapters ─> normalized RiskSignal list
Attachment Analysis (static findings) ────────────────────────────┘                    │
                                                                      consolidate (one contribution per group)
                                                                                       │
                                                                      category caps -> sum, cap at 100 -> level -> action
                                                                                       ▼
                                                                         Explainable assessment (deterministic)
```

| Module | Responsibility |
|---|---|
| `rules.py` | The scoring table in one place: `RISK_WEIGHTS` (a documented rationale per weight), `CONSOLIDATION_GROUPS`, `CATEGORY_CAPS`, confidence factors, thresholds, action mapping, source and category vocabularies, `ENGINE_VERSION`. Prototype heuristic values, not calibrated. Stdlib only. |
| `signals.py` | The normalized `RiskSignal`: code, category, source, title, message, why, evidence, confidence, points, severity, group, analyzer, base_points, capped, related_signal_codes, corroborating_sources. |
| `adapters.py` | Analyzer output -> signals. Decides what evidence exists and where it came from (`rule`, `synthetic_baseline`, `AI`, `fallback`, `attachment_static`, `system`). No scoring numbers. |
| `engine.py` | `collect_signals` (adapters), `consolidate` (deterministic deduplication), category caps, `correlate_signals(signals, inputs)` (the single scoring path) and `correlate_risk(...)` (= collect + correlate). Pure, no I/O. Never raises on missing input. Does not import the analyzers. |
| `service.py` | `assess_incident_risk(incident, attachment_file=None)`: the **only** module that imports the analyzers. A message-analysis failure becomes "unavailable" evidence, not a failed request. |

Categories: IDENTITY, COMMUNICATION, FINANCIAL, BENEFICIARY, BEHAVIOUR, SOCIAL_ENGINEERING, ATTACHMENT; none is required, and missing evidence is never suspicious by itself.

Deduplication rules (visible in `rules.CONSOLIDATION_GROUPS`, tested): a code counts once; signals in the same group describe the same evidence, so only the strongest is scored and the others are kept as `related_signal_codes`. Groups: time pressure (urgency / high urgency / deadline), concealment (secrecy / isolation), payment request (transfer intent / payment pressure), authority (claim / mismatch), channel (unusual / rare), attachment executable (executable / risky extension), attachment disguise (document-looking / double extension), attachment structure. Category caps then bound BEHAVIOUR (20), SOCIAL_ENGINEERING (30) and ATTACHMENT (40). Social-engineering weights scale with the indicator's confidence.

Rules: the correlation layer sits **above** the analyzers, which stay independently usable (AST-tested); no LLM is consulted for any point, level or action (an AI indicator is only evidence, labelled `AI`, and its quote must exist in the message); the engine only recommends and never blocks or executes a payment. Because `correlate_signals` takes normalized signals, a future "same incident with signal X removed" run needs no new scoring code. Scores are heuristic risk points, not probabilities. `POST /api/incidents/{id}/analyze-risk` takes an optional multipart `file`, is computed on demand and its result is persisted as a new immutable assessment (below).

### Persisted risk assessment (v0.6.0)

```
message_analysis ┐
behaviour        ├─> risk_correlation (pure) ─> risk_repository (SQL) ─> incident detail / list / dashboard
attachment (mem) ┘                                  risk_assessments table
```

`POST /analyze-risk` runs `assess_incident_risk`, turns the result into a dict and calls `risk_repository.save_risk_assessment`. The engine has no SQL, HTTP, filesystem, LLM or payment code (AST-tested). Table `risk_assessments` holds the latest snapshot per incident (`incident_id UNIQUE`, upsert), with scalar columns for the headline numbers and JSON text for signals, inputs, thresholds and notes, plus `assessment_version` and `assessed_at`. **Assessment history (0.8.0).** Every run appends one row to `risk_assessment_history` (version 1, 2, 3 per incident, computed inside the INSERT so concurrent runs cannot collide; `UNIQUE (incident_id, version_number)`); rows are never updated (trigger). The latest is the highest version (view `latest_risk_assessments`, used by the list, dashboard counts and incident status). `risk_assessments` is the pre-0.8.0 snapshot table, now read-only, used once to backfill v1 when an older database is opened. A case decision reads only the *identity* of the latest assessment and stores it in `case_actions.assessment_id`; it never changes an assessment. The API field `assessment_version` is the legacy name of `engine_version`; the sequence number is `version_number`.

Before saving, the router calls `risk_repository.check_result_consistent` (score = min(cap, sum of signal points), category points match the signals, level matches the thresholds, action matches the level, no duplicate category); a self-contradicting result is refused and nothing is written (0.7.5). Since 0.7.4 `inputs.message` also records `analysis_state`, `provider` and `failure_kind` (provenance only; no scoring path reads them). Uploaded bytes are analyzed in memory and never stored. An incomplete result (message analysis unavailable) is returned with `persisted: false` and not saved. `services/risk_correlation/incident_status.py` maps level to incident status: LOW -> `proceed`, MEDIUM/HIGH -> `verify`, CRITICAL -> `hold_payment`, none -> `not_assessed` (a recommendation to a human; nothing is blocked). The list endpoint LEFT JOINs the latest assessment (no N+1) and `GET /api/incidents/risk-summary` counts levels in SQL.

### Case workflow (v0.7.0)

```
risk assessment (immutable evidence)         risk_assessments table
        │  (read-only for the analyst)
        ▼
case review  OPEN ──analyst decision──> VERIFIED | REJECTED
router -> services/case_workflow -> case_repository -> case_actions table (append-only)
```

Two separate concerns: **risk level** is what TrustBreak calculated; **workflow status** is what a human recorded. They never derive from each other, and the risk engine does not import the workflow (AST-tested). `case_actions` rows are append-only (an UPDATE trigger aborts; unique partial indexes allow one decision per incident); the current status is the latest row's `new_status`, so it cannot drift from the audit trail. `record_decision` runs `BEGIN IMMEDIATE`, checks the incident exists, reads the current status, validates `OPEN -> VERIFIED|REJECTED`, appends the row and commits (rollback on any error); a closed case is `409 case_already_closed`. New incidents get a `CASE_OPENED` row inside the creation transaction; older databases are backfilled at startup. A decision is a record only: no payment is approved, rejected, blocked, cancelled or executed.

### The analysis seam

`analyze_incident` is the single place future detection plugs in. Today it is still a placeholder (the risk correlation engine runs on demand beside it; since 0.6.0 its result is persisted and is the incident's real status, while this placeholder is kept only as an intake note): it returns `risk_status = "needs_review"`, a fixed recommended action, and evidence items that are the submitted facts (`source = "submitted"`). The result is computed once at creation and stored with the incident. Replacing it with real analysis should not change the router, the schemas' envelope, or the frontend's data flow.

## Trusted identity and evidence graph (0.9.0)
`services/identity/` holds the synthetic `TrustedIdentity` registry (stdlib only). Incidents link to an identity through `incidents.sender_identity_id` (source `explicit`, `name_match` or `none`); `behaviour` derives its profiles from the registry and prefers the id. `services/evidence_graph.py` is a pure builder: identity baseline + behaviour checks + the latest stored assessment's signals -> nodes, edges and EXPECTED-vs-OBSERVED rows, served read-only by `GET /api/incidents/{id}/trust-graph`. It never scores, never calls an AI and the verdict node only repeats the stored assessment.

## Data model

Table `incidents` (flat columns; the API nests them), since 0.6.0 `risk_assessments` (latest assessment per incident, described above) and since 0.7.0 `case_actions` (append-only workflow audit: `incident_id, previous_status, new_status, decision, reason, analyst_name, created_at`):

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

Incident detail (`GET /api/incidents/{id}`) returns nested `sender`, `payment`, `attachment` (nullable), `analysis { mode, risk_status, summary, recommended_action, evidence[] }` (the stored intake placeholder), and since 0.6.0 `risk_assessment` (nullable), `incident_status` and `incident_status_label`. List rows are flat summaries that also carry the latest risk level / action / status (or `not_assessed`). Since 0.7.0 detail also returns `workflow_status`, `workflow_status_label` and `case_history[]`, list rows carry `workflow_status(_label)`, `POST /api/incidents/{id}/decision` records an analyst decision (`409 case_already_closed` when closed) and `GET /api/incidents/case-summary` returns open / verified / rejected counts.

## Product layer (0.13.0)

All additions extend the existing flow; nothing replaces the Risk Engine.

| Module | Role |
|---|---|
| `services/counterfactual.py` | Rebuilds `RiskSignal`s from the latest stored assessment, removes one evidence group (or a combination) and calls `correlate_signals` again. Read-only; no persistence |
| `services/scenarios.py` + `routers/scenarios.py` | 7 synthetic input definitions; loading creates a normal incident (`scenario_id`) and runs `assess_incident_risk` + `save_risk_assessment` |
| `services/verification.py` + `verification_repository.py` | Append-only verification audit (`verification_events`); state derived from the last row; independent of assessments and case decisions |
| `services/timeline.py` | Deterministic merge of incident, assessment history, verification and case audit rows; timestamps are never invented |
| `services/dashboard.py` + `routers/dashboard.py` | Read-only aggregates and honest AI status (configuration + last persisted extraction state) |
| `services/report.py` | Escaped, self-contained printable HTML report served by `GET /api/incidents/{id}/report` |

## Frontend (`frontend/src/`)

| Path | Role |
|---|---|
| `api/client.js` | `fetch` wrapper; throws `ApiError` (`code`, `status`, `details`) |
| `hooks/useAsync.js` | Load/error/reload with abort on unmount |
| `lib/` | `format.js` (₹ en-IN, dates, bytes), `risk.js` (status display), `caseWorkflow.js` (case status/event labels, decision validation), `validation.js` (form rules mirroring the backend) |
| `components/` | `Layout`, `ui` (Card, Button, PageHeader…), `StatusBadge` (Risk + Case badges), `CaseReviewCard` (decision form + history timeline), `States` (loading/error/empty) |
| `pages/` | `Dashboard` (command center), `IncidentList`, `IncidentDetail` (analyst workspace), `CreateIncident`, `Scenarios`, `Identities` |
| 0.13.0 components | `CounterfactualCard`, `VerificationCard`, `TimelineCard`, `EvidenceChainCard` (wraps the existing evidence graph data), `MessageIntelligenceCard`, `AttachmentIntelligenceCard` |

Pages that display data are split into a fetching component and a pure `*View` component, so rendering can be tested without a server.

## Deliberate non-goals (this phase)

No authentication or roles (analyst names are free text), no case reopening/comments, no assessment history, no fraud verdict (AI only extracts message fields; behaviour analysis only emits signals from synthetic profiles), no stored behavioural history, no stored files (attachments are analyzed in memory and discarded), no external integrations (banking, WhatsApp), no payment processing, no migrations tooling.

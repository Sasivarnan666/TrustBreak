# Roadmap

Status legend: **DONE** = exists in code and is tested; **IN PROGRESS** = being built; **NEXT** = the next phase; **LATER** = planned, not started. Version: 0.13.0.

## Phase plan (P0 reliability -> P4 stretch)

| Phase | Item | Status |
|---|---|---|
| P0.1 | Gemini resilience (classified failures, ai / fallback / mock / skipped states) | **DONE** (0.7.4) |
| P0.2 | Assessment correctness audit and pre-persistence guard | **DONE** (0.7.5) |
| P0.3 | Documentation drift (single version source, README / ROADMAP / ARCHITECTURE sync, doc-sync test) | **DONE** (0.7.6) |
| P0.4 | Test integrity (clean-env run, coverage audit, regression gaps) | **DONE** (0.7.7) |
| P1.1 | Assessment history + decision-to-assessment linkage (ROADMAP 7c) | **DONE** (0.8.0) |
| P1.2 | Trusted identity model (`sender_identity_id`, identity context card) | **DONE** (0.9.0) |
| P1.3 | Evidence / trust graph | **DONE** (0.9.0) |
| P1.4 | Behaviour baseline 2.0 (synthetic history, metrics, 8 behavioural signals, evidence UI) | **DONE** (0.10.0; scored since 0.12.0) |
| P1.5 | Social-engineering signal analysis (11 evidence signals, AI/rule/fallback provenance) | **DONE** (0.11.0; scored since 0.12.0) |
| P1.6 | Risk Engine 2.0 + signal provenance (normalized signals, deterministic deduplication, centralized prototype weights, category grouping UI) | **DONE** (0.12.0) |
| P1.7 | Counterfactual risk analysis (read-only what-ifs through the same engine) | **DONE** (0.13.0) |
| P1.8 | Scenario simulator / demo mode (7 synthetic scenarios through the real pipeline) | **DONE** (0.13.0) |
| P1.9 | Independent verification workflow, forensic timeline, analyst command-center dashboard, analyst workspace UI, printable incident report | **DONE** (0.13.0) |
| P1 | Remaining: attachment 2.0 | **NEXT** |
| P2 | Multilingual, channel trust, API quality, security hardening (authentication), performance | LATER |
| P3 | AI observability, summary generation, PDF generation (the report is browser-printable HTML today), search and filtering | LATER |
| P4 | Optional advanced features | LATER |

## Original feature sequence (historical, kept for context)

Each step is independent enough to ship on its own. Built: steps 0, 4, 5, 6a, 7, 7a, 7b (and 7b+/7b++ below); everything else in this table is not started.

| # | Step | Outcome |
|---|---|---|
| 0 | **Foundation** (v0.1.0) | Full-stack flow with placeholder analysis. Built; needs first verification on a networked machine (see PROJECT_STATE). |
| 1 | **Trusted profiles + channel consistency (rule-based)** | Per-sender profile of expected channels/contacts; incident checked against it; explainable evidence; real risk levels. |
| 2 | **Payment-detail consistency** | Beneficiary history (new vs known), amount versus the sender's usual range, mismatch between named payee and instruction. |
| 3 | **Attachment risk indicators (metadata level)** | Flags from name/type/size: archives, executable or double extensions, unexpected attachment for the request type. |
| 4 | **Case workflow & analyst decision audit** (v0.7.0) | **DONE.** Workflow status OPEN / VERIFIED / REJECTED, separate from risk level; `POST /api/incidents/{id}/decision` with a required reason and analyst name; append-only `case_actions` audit trail with explicit transitions (closed cases answer 409); Case review card, history timeline, list column and dashboard counts. A workflow record only: no payment is acted on and the risk assessment is never changed. No authentication, reopening or comments. |
| 5 | **Historical behaviour baseline** (v0.3.0) | **DONE.** Synthetic per-employee profile; deterministic amount / new-beneficiary / unusual-channel signals via `analyze_behaviour`. Signals only, no scoring. Frequency analysis still future work; a statistical baseline and persistent profiles are not built. |
| 6a | **AI message entity & financial-intent extraction** (v0.2.0) | **DONE.** Structured fields (authority, action, amount, beneficiary, urgency, secrecy, deadline, intent) extracted by AI with a labelled demo fallback. Extraction only; consumed by later steps via `analyze_message`. |
| 6 | **AI-assisted message analysis** | LLM review of urgency, secrecy and pressure language, with explanations; clearly labelled as AI output and combined with the rule results. Not started beyond the extraction in 6a. |
| 7 | **Attachment content analysis** (v0.4.0) | **DONE.** Safe, static analysis of an uploaded file: signature-based type detection, ZIP directory inspection (never extracted), executable/script/shortcut denylist, double extensions, document-looking name with executable content, path traversal, nested/encrypted archives, compression-ratio warning. Structural evidence only, no scoring. No sandbox or dynamic analysis; entry contents are not read. |
| 7a | **Risk correlation engine** (v0.5.0) | **DONE.** Deterministic, explainable correlation of message, behaviour and attachment outputs into heuristic risk points, a LOW / MEDIUM / HIGH / CRITICAL level (prototype thresholds) and a `PROCEED` / `VERIFY` / `HOLD_PAYMENT` recommendation, with per-signal evidence. On-demand and not persisted; recommends only, never blocks a payment. Weights are uncalibrated and behaviour data is synthetic. |
| 7b | **Persisted risk assessment & real incident status** (v0.6.0) | **DONE.** The latest assessment is stored per incident (`risk_assessments`, assessment version `0.6.0`) and becomes the incident status (LOW -> proceed, MEDIUM/HIGH -> verify, CRITICAL -> hold_payment, otherwise Not assessed) on the detail page, incident list and dashboard. Latest snapshot only (no history); recommends only. |
| 7b+ | **Gemini resilience** (v0.7.4, P0.1) | **DONE.** Classified AI failures (429, auth, model, timeout, 5xx, network, empty, invalid), explicit ai / fallback / mock / skipped states, fallback disclosed in risk inputs. Live Gemini still unverified. |
| 7b++ | **Assessment correctness audit** (v0.7.5, P0.2) | **DONE.** Backend-authoritative score verified; pre-persistence consistency guard; invariants tested. Deferred to P1: attachment-signal overlap, re-run-without-file downgrade, `engine_version`. |
| 7c | **Assessment history & decision-to-assessment linkage** (**DONE in 0.8.0**) | Keep every risk assessment run (not only the latest) and store on each analyst decision which assessment it reviewed (id, version, time, level, score). Today a re-run replaces the evidence behind an earlier decision and the audit row cannot say what the analyst saw. |
| 8 | **Ingestion and integrations** | Email / messaging ingestion, authentication and roles. |

Principles that stay fixed: every verdict must be explainable from visible evidence; placeholder or heuristic output is always labelled as such; frontend and backend stay separated behind the REST contract.

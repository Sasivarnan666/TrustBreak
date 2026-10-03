# Roadmap

Planned feature sequence. Each step is independent enough to ship on its own, and each builds on the `analyze_incident` seam. Only step 0, step 6a, step 5 (behaviour baseline), step 7 (attachment analysis), step 7a (risk correlation engine) and step 7b (persisted assessment) are built; everything else is not started.

| # | Step | Outcome |
|---|---|---|
| 0 | **Foundation** (v0.1.0) | Full-stack flow with placeholder analysis. Built; needs first verification on a networked machine (see PROJECT_STATE). |
| 1 | **Trusted profiles + channel consistency (rule-based)** | Per-sender profile of expected channels/contacts; incident checked against it; explainable evidence; real risk levels. |
| 2 | **Payment-detail consistency** | Beneficiary history (new vs known), amount versus the sender's usual range, mismatch between named payee and instruction. |
| 3 | **Attachment risk indicators (metadata level)** | Flags from name/type/size: archives, executable or double extensions, unexpected attachment for the request type. |
| 4 | **Case workflow** (**next recommended**) | A human decision on the recommendation: statuses (open / verified / rejected), analyst notes, audit trail, approve/reject with reason. Unblocked by v0.6.0. |
| 5 | **Historical behaviour baseline** (v0.3.0) | **DONE.** Synthetic per-employee profile; deterministic amount / new-beneficiary / unusual-channel signals via `analyze_behaviour`. Signals only, no scoring. Frequency analysis still future work; a statistical baseline and persistent profiles are not built. |
| 6a | **AI message entity & financial-intent extraction** (v0.2.0) | **DONE.** Structured fields (authority, action, amount, beneficiary, urgency, secrecy, deadline, intent) extracted by AI with a labelled demo fallback. Extraction only; consumed by later steps via `analyze_message`. |
| 6 | **AI-assisted message analysis** | LLM review of urgency, secrecy and pressure language, with explanations; clearly labelled as AI output and combined with the rule results. Not started beyond the extraction in 6a. |
| 7 | **Attachment content analysis** (v0.4.0) | **DONE.** Safe, static analysis of an uploaded file: signature-based type detection, ZIP directory inspection (never extracted), executable/script/shortcut denylist, double extensions, document-looking name with executable content, path traversal, nested/encrypted archives, compression-ratio warning. Structural evidence only, no scoring. No sandbox or dynamic analysis; entry contents are not read. |
| 7a | **Risk correlation engine** (v0.5.0) | **DONE.** Deterministic, explainable correlation of message, behaviour and attachment outputs into heuristic risk points, a LOW / MEDIUM / HIGH / CRITICAL level (prototype thresholds) and a `PROCEED` / `VERIFY` / `HOLD_PAYMENT` recommendation, with per-signal evidence. On-demand and not persisted; recommends only, never blocks a payment. Weights are uncalibrated and behaviour data is synthetic. |
| 7b | **Persisted risk assessment & real incident status** (v0.6.0) | **DONE.** The latest assessment is stored per incident (`risk_assessments`, assessment version `0.6.0`) and becomes the incident status (LOW -> proceed, MEDIUM/HIGH -> verify, CRITICAL -> hold_payment, otherwise Not assessed) on the detail page, incident list and dashboard. Latest snapshot only (no history); recommends only. |
| 8 | **Ingestion and integrations** | Email / messaging ingestion, authentication and roles. |

Principles that stay fixed: every verdict must be explainable from visible evidence; placeholder or heuristic output is always labelled as such; frontend and backend stay separated behind the REST contract.

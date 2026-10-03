# Roadmap

Planned feature sequence. Each step is independent enough to ship on its own, and each builds on the `analyze_incident` seam. Nothing below step 0 is started.

| # | Step | Outcome |
|---|---|---|
| 0 | **Foundation** (v0.1.0) | Full-stack flow with placeholder analysis. Built; needs first verification on a networked machine (see PROJECT_STATE). |
| 1 | **Trusted profiles + channel consistency (rule-based)** | Per-sender profile of expected channels/contacts; incident checked against it; explainable evidence; real risk levels. |
| 2 | **Payment-detail consistency** | Beneficiary history (new vs known), amount versus the sender's usual range, mismatch between named payee and instruction. |
| 3 | **Attachment risk indicators (metadata level)** | Flags from name/type/size: archives, executable or double extensions, unexpected attachment for the request type. |
| 4 | **Case workflow** | Statuses (open / verified / rejected), analyst notes, audit trail, approve/reject with reason. |
| 5 | **Historical behaviour baseline** | Statistical baseline per sender and channel; deviation scoring. |
| 6 | **AI-assisted message analysis** | LLM review of urgency, secrecy and pressure language, with explanations; clearly labelled as AI output and combined with the rule results. |
| 7 | **Attachment content analysis** | Sandboxed static inspection of uploaded files. |
| 8 | **Ingestion and integrations** | Email / messaging ingestion, authentication and roles. |

Principles that stay fixed: every verdict must be explainable from visible evidence; placeholder or heuristic output is always labelled as such; frontend and backend stay separated behind the REST contract.

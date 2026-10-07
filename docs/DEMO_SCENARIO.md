# Demo scenario

A synthetic CEO-impersonation-style payment request. Every name, number and message is fictional.

## The incident

| Field | Value |
|---|---|
| Sender | Arvind Rao, Chief Executive Officer (**known contact**) |
| Sender contact | +91 90000 12345 (fictional) |
| Channel | **WhatsApp** |
| Amount | **₹18,50,000** |
| Beneficiary | **New Vendor X** (new beneficiary) |
| Message | Urgent request to release the payment today before 4 PM, citing a regulatory settlement and asking for confidentiality |
| Attachment | **RBI_Statement.zip** (application/zip, about 2.4 MB) - metadata only |

It is inserted automatically as **TB-0001** the first time the backend starts on an empty database.

## Why it is interesting (the TrustBreak idea)

The sender is *known*, so a "known vs unknown sender" check would pass. The questions TrustBreak is built to ask are about **consistency**: is a high-value instruction from this executive normally made over WhatsApp, to a payee never used before, with a zipped "statement" attached, under time pressure? Those checks are **roadmap items**. In this build, the incident is only recorded and flagged for manual review.

## Walkthrough (about 2 minutes)

1. **Dashboard** (`/`) - KPIs show the counts of persisted risk assessments (initially 1 incident, 1 Not assessed, zeros elsewhere).
2. **Incidents** (`/incidents`) - the row shows sender with a *Known* tag, WhatsApp, ₹18,50,000, *New* beneficiary, attachment, and the risk state (*Not assessed* until an assessment is run; see the v0.6.0 demo below).
3. **Incident detail** (click TB-0001) - read top to bottom: risk state, summary strip, the **TrustBreak Risk Assessment** card (Not assessed until run), an intake note while unassessed, the message, the evidence table (submitted facts), sender, payment and attachment cards.
4. **New incident** (`/incidents/new`) - click **Load demo scenario** to pre-fill the same data, or enter your own. Submit with an empty amount to show validation; stop the backend and submit to show the error state.
5. After submitting you land on the new incident's detail page, and the dashboard counts update.

## Attachment analysis demo (v0.4.0)

Run `python scripts/make_demo_attachment.py` to create the inert synthetic `RBI_Statement.zip` (three text files named `Statement.pdf`, `Update.exe`, `helper.dll`). On TB-0001 open **Attachment Analysis**, choose that file and click **Analyze file**: it reports a 3-file ZIP with executable content, 🔴 `Update.exe`, 🔴 `helper.dll` and 🟠 a document-looking archive, with the notice that this is structural analysis only. Nothing is executed or stored.

## Risk assessment demo (v0.5.0)

On TB-0001 click **Run risk assessment** in the **TrustBreak Risk Assessment** card (top of the page). With the demo data and no file it shows **93 risk points, CRITICAL, HOLD PAYMENT** and **TRUST BREAK DETECTED**: amount above baseline (+20), new beneficiary (+20), unusual channel (+15), high urgency (+10), secrecy (+10), financial transfer request (+10). Choose `RBI_Statement.zip` once in **Attachment Analysis**, then click **Run again** on the risk card: executable content (+25) and a document-looking archive with executables (+20) are added; the raw sum is 130, displayed as 100 (capped). Nothing is hard-coded: the result is computed from the three analyzers' outputs. Say: "This is a prototype risk assessment based on correlated indicators. It is not proof of fraud, the points are not probabilities, and nothing is blocked."

## Persisted assessment demo (v0.6.0)

1. Open **Incidents** (`/incidents`): TB-0001 shows **Not assessed** (no placeholder status). The dashboard shows Not assessed 1 and zeros for the levels.
2. Open TB-0001, click **Run risk assessment**: **CRITICAL**, **HOLD PAYMENT**, **TRUST BREAK DETECTED**, 93 risk points, with the assessment time and version.
3. **Refresh the page**: the same assessment is still there; nothing needs to be re-run. Restarting the backend keeps it too (it is in SQLite).
4. Back on **Incidents** and the **Dashboard**: TB-0001 shows CRITICAL / Hold payment and the Critical KPI is 1.
5. **Run again** (optionally with `RBI_Statement.zip` chosen in Attachment Analysis) replaces the stored snapshot (100 points); the zip itself is never stored.
6. Create a normal ₹1,00,000 Email payment to Vendor A from Arvind Rao and assess it: **LOW / PROCEED**.

## Case review demo (v0.7.0)

1. Open TB-0001 and click **Run risk assessment** (as above): **CRITICAL / HOLD PAYMENT**. The header now shows two badges, the red **CRITICAL** (TrustBreak's assessment) and the sky-blue **Case · Open** (analyst workflow). The Incidents list has separate **Risk** and **Case** columns; the Dashboard shows the risk KPIs plus **Open cases 1 / Verified 0 / Rejected 0**.
2. Scroll to **Case review**: status Open, risk level CRITICAL, recommended action Hold payment. Click **Mark verified** with nothing typed: it asks for the analyst name and a reason (at least 10 characters).
3. Enter "Security Analyst" and "Confirmed the request with the sender through the corporate directory number." and click **Mark verified** (or **Reject case** to show the other branch). The badge becomes **Case · Verified**, the controls are disabled with "This case is closed", and the **Case history** timeline shows CASE OPENED then ANALYST VERIFIED with the analyst and reason.
4. **Refresh the page**: still **CRITICAL** + **Case · Verified**, the same assessment (score, signals, time, version) and the same history. The list and dashboard show CRITICAL / Verified and Verified cases 1.
5. Say: "The risk assessment is what TrustBreak calculated and it never changes when a human decides. The decision is an audit record - an analyst said they verified the request. TrustBreak did not verify, approve or block any payment."
6. Optional: `curl -X POST .../api/incidents/1/decision` again returns `409 case_already_closed`.

## What to say about the placeholder

"The pipeline is real - form to API to database to dashboard - but the original intake note is a stub, which is why it is no longer a status. The status now comes from the stored, explainable risk assessment."

## Risk Engine 2.0 demo (v0.12.0)

Scores below come from signals, not constants, and are **prototype heuristic risk points** (not a probability of fraud).

1. On TB-0001 click **Run risk assessment** (no file): **CRITICAL / HOLD PAYMENT / TRUST BREAK DETECTED**, 93 points. Evidence is grouped by category: Financial (amount above baseline +20, transfer request +8), Beneficiary (new beneficiary +20), Communication (unusual channel +15), Social engineering (secrecy +10, verification suppression +9, deadline pressure +8, impersonation cue +3; capped at 30). Each signal shows its source (here "Fallback (not AI)" for message wording when no AI key is set, "Synthetic behavioural baseline" for behaviour), the quoted evidence and a "counted once" line for overlapping indicators (secrecy, urgency and deadline wording are not scored twice).
2. Choose `RBI_Statement.zip` in Attachment Analysis and run again: an Attachment group appears (executable content +25, document-looking archive +12, "static attachment analysis"). Raw points are 130; the displayed score is capped at 100 and the card says so. Assessment v2 is appended; v1 is unchanged.
3. Record a human decision (VERIFIED / REJECTED). It is the case workflow's decision, separate from the engine's HOLD_PAYMENT recommendation, and it links to the exact assessment reviewed; a stale assessment is refused with a 409.
4. Benign comparison: create an incident for Arvind Rao, Email, Vendor A, INR 1,00,000, "Please pay the monthly invoice as usual." It scores 8, **LOW / PROCEED** (only the ordinary "a payment is requested" point).


## Final demo script (0.13.0, about 4 minutes, works without Gemini)

1. **Dashboard** (`/`): tagline, KPIs, and the System status card. With no key or with Gemini unavailable it reads "AI unavailable - deterministic fallback active"; that is the deterministic path, not a failure.
2. **Scenarios** (`/scenarios`, DEMO MODE): click **LOAD SCENARIO** on *Executive Payment Impersonation*. The real pipeline runs with a synthetic `RBI_Statement.zip` (Statement.pdf, Update.exe, helper.dll) and you land on the incident: CRITICAL, 100 (130 raw points), HOLD PAYMENT, TRUST BREAK DETECTED. The numbers come from the engine.
3. **Why did trust break?**: expected vs observed chain, then the evidence graph. **Risk breakdown** shows each signal with its source.
4. **What would reduce the risk?**: removing the attachment evidence or the social-engineering pressure lowers raw points; the displayed score stays high because it is capped, and the combination line shows the smallest change that lowers the level.
5. **Message intelligence** marks the verbatim evidence; **Attachment intelligence** says "static structural analysis only".
6. **Verification**: start with *Known corporate phone*, then record the outcome. Never the WhatsApp number. The **Forensic timeline** updates.
7. **Analyst decision** (VERIFIED / REJECTED with reason) is separate; **EXPORT INCIDENT REPORT** opens the printable report.
8. Contrast: load *Legitimate High-Value Payment* (LOW, PROCEED) and *Suspicious but Legitimate Request* (flagged for verification, not treated as fraud).

Primary demo data: Arvind Rao, CEO, NovaTech Industries, WhatsApp, ₹18,50,000, New Vendor X. Benign: Arvind Rao, Email, Vendor A, ₹1,00,000, routine wording (create it from **New incident**).

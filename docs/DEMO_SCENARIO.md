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

On TB-0001 click **Run risk assessment** in the **TrustBreak Risk Assessment** card (top of the page). With the demo data and no file it shows **85 risk points, CRITICAL, HOLD PAYMENT** and **TRUST BREAK DETECTED**: amount above baseline (+20), new beneficiary (+20), unusual channel (+15), high urgency (+10), secrecy (+10), financial transfer request (+10). Choose `RBI_Statement.zip` once in **Attachment Analysis**, then click **Run again** on the risk card: executable content (+25) and a document-looking archive with executables (+20) are added; the raw sum is 130, displayed as 100 (capped). Nothing is hard-coded: the result is computed from the three analyzers' outputs. Say: "This is a prototype risk assessment based on correlated indicators. It is not proof of fraud, the points are not probabilities, and nothing is blocked."

## Persisted assessment demo (v0.6.0)

1. Open **Incidents** (`/incidents`): TB-0001 shows **Not assessed** (no placeholder status). The dashboard shows Not assessed 1 and zeros for the levels.
2. Open TB-0001, click **Run risk assessment**: **CRITICAL**, **HOLD PAYMENT**, **TRUST BREAK DETECTED**, 85 risk points, with the assessment time and version.
3. **Refresh the page**: the same assessment is still there; nothing needs to be re-run. Restarting the backend keeps it too (it is in SQLite).
4. Back on **Incidents** and the **Dashboard**: TB-0001 shows CRITICAL / Hold payment and the Critical KPI is 1.
5. **Run again** (optionally with `RBI_Statement.zip` chosen in Attachment Analysis) replaces the stored snapshot (100 points); the zip itself is never stored.
6. Create a normal ₹1,00,000 Email payment to Vendor A from Arvind Rao and assess it: **LOW / PROCEED**.

## What to say about the placeholder

"The pipeline is real - form to API to database to dashboard - but the original intake note is a stub, which is why it is no longer a status. The status now comes from the stored, explainable risk assessment."

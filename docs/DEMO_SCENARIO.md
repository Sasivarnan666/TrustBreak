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

1. **Dashboard** (`/`) - KPIs show 1 incident, 1 needing review, ₹18,50,000 under review, 1 new beneficiary. The "Analysis engine" card states plainly that analysis is a placeholder.
2. **Incidents** (`/incidents`) - the row shows sender with a *Known* tag, WhatsApp, ₹18,50,000, *New* beneficiary, attachment, *Needs review*.
3. **Incident detail** (click TB-0001) - read top to bottom: status, summary strip, **Recommended action** (hold the payment; verify through a number from your own records), the message, the evidence table (submitted facts), sender, payment and attachment cards.
4. **New incident** (`/incidents/new`) - click **Load demo scenario** to pre-fill the same data, or enter your own. Submit with an empty amount to show validation; stop the backend and submit to show the error state.
5. After submitting you land on the new incident's detail page, and the dashboard counts update.

## What to say about the placeholder

"The pipeline is real - form to API to database to dashboard - but the verdict is a stub. We record the facts and recommend manual verification. The consistency engine is the next phase."

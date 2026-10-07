"""Synthetic demo scenarios (P2). Every name, number, message and file here is fictional.

A scenario only supplies INPUT (sender, channel, amount, beneficiary, message, optional synthetic archive). The
risk level, score and recommended action are never stored here: loading a scenario creates a normal incident and
runs the real pipeline (extraction -> behaviour -> attachment -> Risk Engine), so results emerge from the engine.
Nothing is executed: a scenario attachment is a tiny in-memory ZIP of harmless placeholder text files that is
analysed statically and discarded.
"""

import io
import zipfile
from dataclasses import dataclass, field
from typing import Optional

ORG = "NovaTech Industries"
SYNTHETIC_LABEL = "Synthetic demo scenario - fictional people, organisation, amounts and files."


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    illustrates: str                      # qualitative description only - NO expected score or level
    sender_name: str
    sender_role: str
    identity_id: Optional[str]
    channel: str
    amount: int
    beneficiary_name: str
    beneficiary_is_new: bool
    message: str
    received_at: Optional[str] = None
    attachment_name: Optional[str] = None
    attachment_entries: tuple = field(default=())   # file names inside the synthetic archive
    sender_contact: Optional[str] = None
    organization: str = ORG

    def incident_payload(self) -> dict:
        data = {
            "sender_name": self.sender_name, "sender_role": self.sender_role, "sender_known": True,
            "sender_contact": self.sender_contact, "sender_identity_id": self.identity_id,
            "channel": self.channel, "amount": self.amount, "beneficiary_name": self.beneficiary_name,
            "beneficiary_is_new": self.beneficiary_is_new, "message": self.message, "received_at": self.received_at,
        }
        if self.attachment_name:
            data.update(attachment_name=self.attachment_name, attachment_content_type="application/zip",
                        attachment_size_bytes=len(self.attachment_bytes() or b""))
        return data

    def attachment_bytes(self) -> Optional[bytes]:
        if not self.attachment_name:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            for entry in self.attachment_entries:
                archive.writestr(entry, "TrustBreak synthetic placeholder - not real content.")
        return buf.getvalue()

    def to_public(self) -> dict:
        return {
            "id": self.id, "title": self.title, "illustrates": self.illustrates, "synthetic": True,
            "synthetic_label": SYNTHETIC_LABEL, "sender_name": self.sender_name, "sender_role": self.sender_role,
            "organization": self.organization, "channel": self.channel, "amount": self.amount,
            "currency": "INR", "beneficiary_name": self.beneficiary_name, "beneficiary_is_new": self.beneficiary_is_new,
            "message": self.message, "received_at": self.received_at, "attachment_name": self.attachment_name,
            "attachment_entries": list(self.attachment_entries),
        }


SCENARIOS = (
    Scenario(
        id="executive_payment_impersonation", title="Executive Payment Impersonation",
        illustrates="A CEO-style request on an informal channel: new beneficiary, pressure, secrecy and an archive with executable content.",
        sender_name="Arvind Rao", sender_role="Chief Executive Officer", identity_id="CEO-001", channel="WhatsApp",
        sender_contact="+91 90000 12345", amount=1_850_000, beneficiary_name="New Vendor X", beneficiary_is_new=True,
        message=("Urgent. I am in a board meeting and cannot take calls. Please release ₹18,50,000 to our new vendor "
                 "today before 4 PM for a regulatory settlement. The RBI statement is attached. Keep this between us "
                 "and confirm once it is done."),
        attachment_name="RBI_Statement.zip", attachment_entries=("Statement.pdf", "Update.exe", "helper.dll"),
    ),
    Scenario(
        id="vendor_bank_detail_change", title="Vendor Bank Detail Change",
        illustrates="A finance request to switch a known vendor to a new bank account while discouraging confirmation with the vendor.",
        sender_name="Meera Iyer", sender_role="Chief Financial Officer", identity_id="CFO-001", channel="Email",
        amount=400_000, beneficiary_name="Vendor D", beneficiary_is_new=False, received_at="2026-10-06T11:15:00+05:30",
        message=("Hi team, Vendor D has told us their bank account has changed. Please update the beneficiary details to "
                 "the new account below before the next payment run. Please do not call the vendor to confirm, their "
                 "finance team is away this week. New account: 000123456789, IFSC TEST0001234."),
    ),
    Scenario(
        id="urgent_invoice_fraud", title="Urgent Invoice Fraud",
        illustrates="A deadline-driven invoice to a never-seen supplier that asks to skip the usual approval.",
        sender_name="Meera Iyer", sender_role="Chief Financial Officer", identity_id="CFO-001", channel="Email",
        amount=950_000, beneficiary_name="Skyline Logistics Pvt Ltd", beneficiary_is_new=True,
        received_at="2026-10-06T16:40:00+05:30",
        message=("Urgent: the attached invoice from Skyline Logistics is overdue and must be paid today before 5 PM or "
                 "we face a penalty. Please process the transfer immediately and skip the usual approval, I will "
                 "regularise it later."),
    ),
    Scenario(
        id="credential_otp_request", title="Credential / OTP Request",
        illustrates="A message from a new number asking for an OTP and portal password, on a channel the sender does not normally use.",
        sender_name="Arvind Rao", sender_role="Chief Executive Officer", identity_id="CEO-001", channel="SMS",
        amount=50_000, beneficiary_name="Vendor A", beneficiary_is_new=False, received_at="2026-10-06T23:10:00+05:30",
        message=("This is Arvind, I am using a new number as I lost my phone. I am locked out of the banking portal. "
                 "Please send me the OTP and the portal password right now so I can approve the vendor payment. Do "
                 "not tell anyone."),
    ),
    Scenario(
        id="suspicious_document_delivery", title="Suspicious Document Delivery",
        illustrates="A routine-sounding payment request whose archive hides an executable behind a document-looking name.",
        sender_name="Meera Iyer", sender_role="Chief Financial Officer", identity_id="CFO-001", channel="Email",
        amount=150_000, beneficiary_name="Vendor B", beneficiary_is_new=False, received_at="2026-10-06T10:30:00+05:30",
        message="Please open the attached Q3 invoice pack and process the payment to Vendor B. The invoice is inside the archive.",
        attachment_name="Invoice_Q3.zip", attachment_entries=("Invoice_Q3.pdf.exe", "notes.txt"),
    ),
    Scenario(
        id="legitimate_high_value_payment", title="Legitimate High-Value Payment",
        illustrates="A large but ordinary payment: known channel, known beneficiary, normal amount for the sender, working hours, calm wording.",
        sender_name="Meera Iyer", sender_role="Chief Financial Officer", identity_id="CFO-001", channel="Email",
        amount=1_150_000, beneficiary_name="Vendor D", beneficiary_is_new=False, received_at="2026-10-06T11:00:00+05:30",
        message=("Hello, please release the quarterly payment of Rs 11,50,000 to Vendor D as per the approved purchase "
                 "order PO-2291. The approval is on file in the ERP. Thanks."),
    ),
    Scenario(
        id="suspicious_but_legitimate_request", title="Suspicious but Legitimate Request",
        illustrates="An unusual but genuine request (new vendor, higher amount) with no pressure: it should be flagged for verification, not treated as fraud.",
        sender_name="Arvind Rao", sender_role="Chief Executive Officer", identity_id="CEO-001", channel="Email",
        amount=350_000, beneficiary_name="Vendor F", beneficiary_is_new=True, received_at="2026-10-06T14:20:00+05:30",
        message=("Hello, we are onboarding Vendor F for the new warehouse fit-out. Please pay the first milestone of "
                 "Rs 3,50,000 once finance has completed vendor verification and the purchase order is approved in "
                 "the ERP. Happy to talk it through if useful."),
    ),
)
BY_ID = {s.id: s for s in SCENARIOS}


def get_scenario(scenario_id: str) -> Optional[Scenario]:
    return BY_ID.get(scenario_id)

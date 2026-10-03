"""Synthetic demo data. Every name, number and message here is fictional."""

import sqlite3

from . import repository
from .schemas import IncidentCreate

DEMO_INCIDENT = IncidentCreate(
    sender_name="Arvind Rao",
    sender_role="Chief Executive Officer",
    sender_known=True,
    sender_contact="+91 90000 12345",
    channel="WhatsApp",
    amount=1_850_000,
    beneficiary_name="New Vendor X",
    beneficiary_is_new=True,
    message=(
        "Urgent. I am in a board meeting and cannot take calls. Please release "
        "₹18,50,000 to our new vendor today before 4 PM for a regulatory settlement. "
        "The RBI statement is attached. Keep this between us and confirm once it is done."
    ),
    attachment_name="RBI_Statement.zip",
    attachment_size_bytes=2_516_582,
    attachment_content_type="application/zip",
)


def seed_if_empty(conn: sqlite3.Connection) -> bool:
    """Insert the demo incident when the table is empty. Returns True if inserted."""
    if repository.count_incidents(conn) > 0:
        return False
    repository.create_incident(conn, DEMO_INCIDENT)
    return True

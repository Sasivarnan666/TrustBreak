"""SQLite access using the standard library only (no ORM).

One short-lived connection per request, handed out by `get_db`.
"""

import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from .config import get_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at              TEXT    NOT NULL,
    title                   TEXT    NOT NULL,

    sender_name             TEXT    NOT NULL,
    sender_role             TEXT    NOT NULL,
    sender_known            INTEGER NOT NULL CHECK (sender_known IN (0, 1)),
    sender_contact          TEXT,

    channel                 TEXT    NOT NULL,

    amount                  INTEGER NOT NULL CHECK (amount > 0),
    currency                TEXT    NOT NULL DEFAULT 'INR',
    beneficiary_name        TEXT    NOT NULL,
    beneficiary_is_new      INTEGER NOT NULL CHECK (beneficiary_is_new IN (0, 1)),

    message                 TEXT    NOT NULL,

    attachment_name         TEXT,
    attachment_size_bytes   INTEGER,
    attachment_content_type TEXT,

    analysis_mode           TEXT    NOT NULL,
    risk_status             TEXT    NOT NULL,
    analysis_summary        TEXT    NOT NULL,
    recommended_action      TEXT    NOT NULL,
    evidence_json           TEXT    NOT NULL
);
"""


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = Path(path) if path else get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may resolve a dependency and run the
    # endpoint on different worker threads; a connection is only ever used by
    # one request at a time.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Optional[Path] = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: yields a connection and always closes it."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()

"""SQLite access using the standard library only (no ORM).

One short-lived connection per request, handed out by `get_db`.
"""

import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from . import case_repository
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
    sender_identity_id      TEXT,    -- v0.9.0: stable trusted-identity id (NULL = none / pre-0.9.0 row)
    sender_identity_source  TEXT,    -- explicit | name_match | none
    received_at             TEXT,    -- 0.10.0: optional ISO-8601 time the request was received (NULL = unknown)
    scenario_id             TEXT,    -- 0.13.0: synthetic demo scenario this incident was created from (NULL = not a scenario)

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

-- v0.6.0: the LATEST risk assessment per incident (one row; running it again replaces the row).
-- Structured parts are JSON text. Uploaded attachment bytes are never stored.
CREATE TABLE IF NOT EXISTS risk_assessments (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id                  INTEGER NOT NULL UNIQUE REFERENCES incidents(id) ON DELETE CASCADE,
    assessment_version           TEXT    NOT NULL,
    assessed_at                  TEXT    NOT NULL,
    risk_score                   INTEGER NOT NULL,
    raw_points                   INTEGER NOT NULL,
    max_score                    INTEGER NOT NULL,
    risk_level                   TEXT    NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    recommended_action           TEXT    NOT NULL,
    incident_status              TEXT    NOT NULL,
    trust_break_detected         INTEGER NOT NULL CHECK (trust_break_detected IN (0, 1)),
    headline                     TEXT    NOT NULL,
    explanation                  TEXT    NOT NULL,
    recommended_action_guidance  TEXT    NOT NULL,
    signals_json                 TEXT    NOT NULL,
    category_points_json         TEXT    NOT NULL,
    inputs_json                  TEXT    NOT NULL,
    thresholds_json              TEXT    NOT NULL,
    notes_json                   TEXT    NOT NULL,
    scoring_method               TEXT    NOT NULL,
    disclaimer                   TEXT    NOT NULL
);

-- v0.8.0: IMMUTABLE assessment history. Every risk run appends one row (version_number 1, 2, 3 ... per incident);
-- rows are never updated. The "latest assessment" is the highest version_number (view latest_risk_assessments).
-- `risk_assessments` above is the pre-0.8.0 single-snapshot table: kept read-only so older databases can be
-- backfilled into this history as version 1; nothing writes to it any more.
CREATE TABLE IF NOT EXISTS risk_assessment_history (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,   -- assessment_id
    incident_id                  INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    version_number               INTEGER NOT NULL CHECK (version_number >= 1),
    engine_version               TEXT    NOT NULL,
    assessed_at                  TEXT    NOT NULL,
    risk_score                   INTEGER NOT NULL,
    raw_points                   INTEGER NOT NULL,
    max_score                    INTEGER NOT NULL,
    risk_level                   TEXT    NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    recommended_action           TEXT    NOT NULL,
    incident_status              TEXT    NOT NULL,
    trust_break_detected         INTEGER NOT NULL CHECK (trust_break_detected IN (0, 1)),
    headline                     TEXT    NOT NULL,
    explanation                  TEXT    NOT NULL,
    recommended_action_guidance  TEXT    NOT NULL,
    signals_json                 TEXT    NOT NULL,
    category_points_json         TEXT    NOT NULL,
    inputs_json                  TEXT    NOT NULL,
    thresholds_json              TEXT    NOT NULL,
    notes_json                   TEXT    NOT NULL,
    scoring_method               TEXT    NOT NULL,
    disclaimer                   TEXT    NOT NULL,
    UNIQUE (incident_id, version_number)
);
CREATE TRIGGER IF NOT EXISTS trg_assessment_history_no_update
BEFORE UPDATE ON risk_assessment_history
BEGIN
    SELECT RAISE(ABORT, 'risk_assessment_history rows are immutable');
END;
CREATE VIEW IF NOT EXISTS latest_risk_assessments AS
    SELECT h.* FROM risk_assessment_history h
    WHERE h.version_number = (SELECT MAX(version_number) FROM risk_assessment_history WHERE incident_id = h.incident_id);

-- v0.7.0: append-only human case workflow / audit trail. The CURRENT workflow status of an incident is the
-- new_status of its latest row (no rows = OPEN). Risk assessments are never touched by this table.
CREATE TABLE IF NOT EXISTS case_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    previous_status TEXT    CHECK (previous_status IS NULL OR previous_status IN ('OPEN', 'VERIFIED', 'REJECTED')),
    new_status      TEXT    NOT NULL CHECK (new_status IN ('OPEN', 'VERIFIED', 'REJECTED')),
    decision        TEXT    NOT NULL CHECK (decision IN ('CASE_OPENED', 'VERIFIED', 'REJECTED')),
    reason          TEXT    NOT NULL,
    analyst_name    TEXT,
    created_at      TEXT    NOT NULL,
    assessment_id   INTEGER REFERENCES risk_assessment_history(id)  -- v0.8.0: the exact assessment a decision was based on
);
CREATE INDEX IF NOT EXISTS idx_case_actions_incident ON case_actions (incident_id, id);
-- At most one analyst decision per case (no reopening in v0.7.0) and one CASE_OPENED row; also closes races.
CREATE UNIQUE INDEX IF NOT EXISTS uq_case_actions_one_decision
    ON case_actions (incident_id) WHERE decision IN ('VERIFIED', 'REJECTED');
CREATE UNIQUE INDEX IF NOT EXISTS uq_case_actions_one_opened
    ON case_actions (incident_id) WHERE decision = 'CASE_OPENED';
-- Audit rows are immutable: any UPDATE is refused.
CREATE TRIGGER IF NOT EXISTS trg_case_actions_no_update
BEFORE UPDATE ON case_actions
BEGIN
    SELECT RAISE(ABORT, 'case_actions rows are immutable');
END;

-- 0.13.0: append-only independent-verification audit trail. Separate from risk assessments and from the final case
-- decision. The CURRENT verification state is the state_after of the latest row (no rows = NOT_STARTED).
CREATE TABLE IF NOT EXISTS verification_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id   INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_type    TEXT    NOT NULL CHECK (event_type IN ('VERIFICATION_STARTED', 'VERIFICATION_CONFIRMED', 'VERIFICATION_FAILED')),
    state_after   TEXT    NOT NULL CHECK (state_after IN ('IN_PROGRESS', 'CONFIRMED', 'FAILED')),
    method        TEXT,
    reason        TEXT    NOT NULL,
    analyst_name  TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    based_on_assessment_id INTEGER REFERENCES risk_assessment_history(id)  -- the assessment current when this was recorded
);
CREATE INDEX IF NOT EXISTS idx_verification_incident ON verification_events (incident_id, id);
CREATE TRIGGER IF NOT EXISTS trg_verification_no_update
BEFORE UPDATE ON verification_events
BEGIN
    SELECT RAISE(ABORT, 'verification_events rows are immutable');
END;
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


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent upgrades for databases created by older versions."""
    inc_cols = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)")}
    if "sender_identity_id" not in inc_cols:  # < 0.9.0
        conn.execute("ALTER TABLE incidents ADD COLUMN sender_identity_id TEXT")
    if "sender_identity_source" not in inc_cols:
        conn.execute("ALTER TABLE incidents ADD COLUMN sender_identity_source TEXT")
    if "received_at" not in inc_cols:  # < 0.10.0
        conn.execute("ALTER TABLE incidents ADD COLUMN received_at TEXT")
    if "scenario_id" not in inc_cols:  # < 0.13.0
        conn.execute("ALTER TABLE incidents ADD COLUMN scenario_id TEXT")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(case_actions)")}
    if "assessment_id" not in columns:  # < 0.8.0
        conn.execute("ALTER TABLE case_actions ADD COLUMN assessment_id INTEGER REFERENCES risk_assessment_history(id)")
    # < 0.8.0 kept one mutable snapshot per incident: carry it over as version 1 (never duplicated).
    conn.execute(
        """
        INSERT INTO risk_assessment_history (
            incident_id, version_number, engine_version, assessed_at, risk_score, raw_points, max_score, risk_level,
            recommended_action, incident_status, trust_break_detected, headline, explanation,
            recommended_action_guidance, signals_json, category_points_json, inputs_json, thresholds_json,
            notes_json, scoring_method, disclaimer)
        SELECT r.incident_id, 1, r.assessment_version, r.assessed_at, r.risk_score, r.raw_points, r.max_score,
               r.risk_level, r.recommended_action, r.incident_status, r.trust_break_detected, r.headline,
               r.explanation, r.recommended_action_guidance, r.signals_json, r.category_points_json, r.inputs_json,
               r.thresholds_json, r.notes_json, r.scoring_method, r.disclaimer
        FROM risk_assessments r
        WHERE NOT EXISTS (SELECT 1 FROM risk_assessment_history h WHERE h.incident_id = r.incident_id)
        """
    )


def init_db(path: Optional[Path] = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        case_repository.backfill_opened(conn)  # incidents created before v0.7.0 get their CASE_OPENED row
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

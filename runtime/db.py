"""
SQLite persistence. The webhook_events table's event_id PRIMARY KEY is what
gives real, DB-enforced idempotency for Failure A (duplicate webhook) - a
second insert of the same event_id raises sqlite3.IntegrityError, not
something we have to remember to check with an in-memory set that a restart
would silently lose.
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "runtime.db"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            reference_id TEXT NOT NULL,
            amount REAL NOT NULL,
            state TEXT NOT NULL,
            razorpay_payment_link_id TEXT,
            days_past_due INTEGER NOT NULL DEFAULT 0,
            contact_note TEXT NOT NULL,
            prior_intervention_count INTEGER NOT NULL DEFAULT 0,
            promised_amount REAL,
            promised_date_days_from_now INTEGER,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            customer_contact TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS webhook_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            received_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            at REAL NOT NULL,
            event_type TEXT NOT NULL,
            detail TEXT NOT NULL
        );
        """
    )
    conn.commit()

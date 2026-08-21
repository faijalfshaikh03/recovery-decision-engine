import sqlite3
import time
from typing import Optional

from runtime.schemas import CaseState, RuntimeCase


def create_case(
    conn: sqlite3.Connection,
    case_id: str,
    reference_id: str,
    amount: float,
    contact_note: str,
    customer_name: str,
    customer_email: str,
    customer_contact: str,
    days_past_due: int = 0,
) -> RuntimeCase:
    now = time.time()
    conn.execute(
        """INSERT INTO cases
           (case_id, reference_id, amount, state, contact_note, days_past_due,
            customer_name, customer_email, customer_contact, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            case_id, reference_id, amount, CaseState.OVERDUE.value, contact_note, days_past_due,
            customer_name, customer_email, customer_contact, now, now,
        ),
    )
    conn.commit()
    return get_case(conn, case_id)


def get_case(conn: sqlite3.Connection, case_id: str) -> Optional[RuntimeCase]:
    row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    return RuntimeCase(
        case_id=row["case_id"],
        reference_id=row["reference_id"],
        amount=row["amount"],
        state=CaseState(row["state"]),
        razorpay_payment_link_id=row["razorpay_payment_link_id"],
        days_past_due=row["days_past_due"],
        contact_note=row["contact_note"],
        prior_intervention_count=row["prior_intervention_count"],
        promised_amount=row["promised_amount"],
        promised_date_days_from_now=row["promised_date_days_from_now"],
        customer_name=row["customer_name"],
        customer_email=row["customer_email"],
        customer_contact=row["customer_contact"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_case_by_payment_link(conn: sqlite3.Connection, payment_link_id: str) -> Optional[RuntimeCase]:
    row = conn.execute(
        "SELECT case_id FROM cases WHERE razorpay_payment_link_id = ?", (payment_link_id,)
    ).fetchone()
    if row is None:
        return None
    return get_case(conn, row["case_id"])


def update_case(conn: sqlite3.Connection, case_id: str, **fields) -> RuntimeCase:
    if not fields:
        return get_case(conn, case_id)
    fields["updated_at"] = time.time()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [case_id]
    conn.execute(f"UPDATE cases SET {set_clause} WHERE case_id = ?", values)
    conn.commit()
    return get_case(conn, case_id)


def log_audit(conn: sqlite3.Connection, case_id: str, event_type: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (case_id, at, event_type, detail) VALUES (?, ?, ?, ?)",
        (case_id, time.time(), event_type, detail),
    )
    conn.commit()


def get_audit_log(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE case_id = ? ORDER BY at ASC", (case_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def record_webhook_event(conn: sqlite3.Connection, event_id: str, event_type: str, payload_json: str) -> bool:
    """Returns True if this was a new event, False if it's a duplicate
    (INSERT into the PRIMARY KEY failed) - the DB itself is the source of
    truth for dedup, not application-level bookkeeping."""
    try:
        conn.execute(
            "INSERT INTO webhook_events (event_id, event_type, payload_json, received_at) VALUES (?, ?, ?, ?)",
            (event_id, event_type, payload_json, time.time()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

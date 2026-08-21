"""
Creates one real case and runs it through the actual system: extraction ->
recommendation -> policy -> real Razorpay action -> verification. Requires
the webhook app (runtime/webhook_app.py) already running so a real payment
webhook can be observed for this case.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from runtime import case_service, case_store, db

conn = db.get_connection()
db.init_db(conn)

case_id = "live_demo_1"
existing = case_store.get_case(conn, case_id)
if existing:
    print(f"Case {case_id} already exists, state={existing.state.value}. Delete data/runtime.db to reset.")
else:
    case = case_store.create_case(
        conn,
        case_id=case_id,
        reference_id="live-demo-1",
        amount=48000.0,
        contact_note="No response yet from the customer regarding the outstanding balance.",
        customer_name="Live Demo Customer",
        customer_email="live-demo@example.com",
        customer_contact="+918123456783",
        days_past_due=22,
    )
    print(f"Created case {case_id}, state={case.state.value}")

print("\nRunning decision...")
result = case_service.run_decision(conn, case_id)
print("Decision result:", result)

updated = case_store.get_case(conn, case_id)
print(f"\nCase state: {updated.state.value}")
if updated.razorpay_payment_link_id:
    print(f"Payment link id: {updated.razorpay_payment_link_id}")

print("\nAudit log:")
for entry in case_store.get_audit_log(conn, case_id):
    print(f"  [{entry['event_type']}] {entry['detail'][:200]}")

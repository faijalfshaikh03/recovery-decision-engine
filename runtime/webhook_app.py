"""
The real webhook endpoint. Signature verification -> DB-enforced dedup ->
fast 2xx ack -> state engine, matching the pattern validated against real
Razorpay traffic in recon/03_webhook_receiver.py, now wired to actual case
state instead of just logging.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from runtime import case_service, db

WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()

app = FastAPI()
_conn = db.get_connection()
db.init_db(_conn)


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    if not WEBHOOK_SECRET:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    event_id = request.headers.get("x-razorpay-event-id", "")

    if not verify_signature(raw_body, signature):
        # Reject before processing (Failure C) - log and drop, still ack
        # fast so Razorpay doesn't retry-storm us over a signature issue.
        print(f"[webhook] REJECTED invalid signature, event_id={event_id}")
        return {"status": "rejected"}

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {"status": "rejected", "reason": "invalid json"}

    event_type = payload.get("event", "unknown")
    result = case_service.apply_webhook_event(_conn, event_id, event_type, payload)
    print(f"[webhook] {event_type} id={event_id} -> {result}")

    return {"status": "ok"}

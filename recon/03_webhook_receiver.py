"""
Recon steps 6-9: minimal webhook receiver.
Verifies X-Razorpay-Signature, extracts x-razorpay-event-id, tests dedup,
logs everything to recon/webhook_log.jsonl for inspection.
"""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()

if not WEBHOOK_SECRET:
    raise SystemExit(
        "RAZORPAY_WEBHOOK_SECRET missing from .env - set it to the same "
        "value you typed into the Razorpay Dashboard webhook secret field."
    )

LOG_PATH = Path(__file__).resolve().parent / "webhook_log.jsonl"
RAW_DIR = Path(__file__).resolve().parent / "raw_bodies"
RAW_DIR.mkdir(exist_ok=True)
seen_event_ids: set[str] = set()

app = FastAPI()


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    event_id = request.headers.get("x-razorpay-event-id", "")

    sig_valid = verify_signature(raw_body, signature)
    is_duplicate = event_id in seen_event_ids
    if event_id:
        seen_event_ids.add(event_id)

    try:
        payload = json.loads(raw_body)
    except Exception:
        payload = {"_raw": raw_body.decode("utf-8", errors="replace")}

    record = {
        "received_at": time.time(),
        "event_id": event_id,
        "signature_present": bool(signature),
        "signature_valid": sig_valid,
        "is_duplicate": is_duplicate,
        "event": payload.get("event"),
        "headers": dict(request.headers),
        "payload": payload,
    }

    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    if event_id and not is_duplicate:
        with open(RAW_DIR / f"{event_id}.raw", "wb") as f:
            f.write(raw_body)
        with open(RAW_DIR / f"{event_id}.sig", "w") as f:
            f.write(signature)

    print(
        f"[webhook] event={payload.get('event')} id={event_id} "
        f"sig_valid={sig_valid} duplicate={is_duplicate}"
    )

    # Always ack fast (2xx within 5s window) regardless of validity -
    # we log invalid/duplicate events rather than hanging Razorpay's retry logic.
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"Logging webhook events to {LOG_PATH}")
    uvicorn.run(app, host="0.0.0.0", port=8787)

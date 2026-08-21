"""
Recon: create a Payment Link with accept_partial=true so we can exercise
payment_link.partially_paid, then payment_link.paid, and observe real webhooks.
"""
import os
import json
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
KEY_ID = os.environ["RAZORPAY_KEY_ID"].strip()
KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"].strip()

if not KEY_ID.startswith("rzp_test_"):
    print("REFUSING TO RUN: not a test-mode key.")
    sys.exit(1)

BASE = "https://api.razorpay.com/v1"
auth = (KEY_ID, KEY_SECRET)

payload = {
    "amount": 4800000,  # 48,000.00 INR total
    "currency": "INR",
    "description": "Recovery case recon-partial-1",
    "reference_id": "recon-partial-1",
    "customer": {
        "name": "Recon Partial Customer",
        "email": "recon-partial@example.com",
        "contact": "+918123456781",
    },
    "notify": {"sms": False, "email": False},
    "reminder_enable": False,
    "accept_partial": True,
    "first_min_partial_amount": 1000000,  # min 10,000.00 INR first payment
}
r = requests.post(f"{BASE}/payment_links", auth=auth, json=payload)
print("status:", r.status_code)
link = r.json()
print(json.dumps(link, indent=2))

if r.status_code in (200, 201):
    with open(Path(__file__).resolve().parent / "last_partial_link.json", "w") as f:
        json.dump({"id": link["id"], "short_url": link["short_url"]}, f, indent=2)
    print(f"\n>>> URL: {link['short_url']}")

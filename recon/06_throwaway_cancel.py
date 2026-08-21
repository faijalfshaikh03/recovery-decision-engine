"""Recon: create a throwaway link and cancel it immediately to get a clean
payment_link.cancelled webhook sample for the dedup replay test."""
import os
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

auth = (KEY_ID, KEY_SECRET)
BASE = "https://api.razorpay.com/v1"

r = requests.post(
    f"{BASE}/payment_links",
    auth=auth,
    json={
        "amount": 100000,
        "currency": "INR",
        "description": "throwaway-for-cancel-webhook-test",
        "reference_id": "recon-throwaway-1",
        "customer": {
            "name": "Throwaway",
            "email": "throwaway@example.com",
            "contact": "+918123456782",
        },
    },
)
link = r.json()
link_id = link["id"]
print("created:", link_id)

r2 = requests.post(f"{BASE}/payment_links/{link_id}/cancel", auth=auth)
print("cancel status:", r2.status_code)
print(r2.json())

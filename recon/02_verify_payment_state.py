"""
Recon step 10: independently verify the payment state via API,
not trusting what the browser checkout UI claimed.
"""
import os
import json
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
KEY_ID = os.environ["RAZORPAY_KEY_ID"].strip()
KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"].strip()
BASE = "https://api.razorpay.com/v1"
auth = (KEY_ID, KEY_SECRET)

with open(Path(__file__).resolve().parent / "last_link.json") as f:
    link_info = json.load(f)

link_id = link_info["id"]

print(f"Fetching Payment Link {link_id} to check status/amount_paid...")
r = requests.get(f"{BASE}/payment_links/{link_id}", auth=auth)
link = r.json()
print(json.dumps(link, indent=2))

payments = link.get("payments") or []
print(f"\nPayment Link status: {link.get('status')}")
print(f"amount_paid: {link.get('amount_paid')}")
print(f"payments attached: {payments}")

if payments:
    payment_id = payments[0]["payment_id"]
    print(f"\nFetching individual payment {payment_id} for ground-truth status...")
    r = requests.get(f"{BASE}/payments/{payment_id}", auth=auth)
    payment = r.json()
    print(json.dumps(payment, indent=2))

"""
Recon step 1-4: verify test-mode auth, create a Payment Link, fetch it back.
Reads credentials from .env - never print key_secret.
"""
import os
import json
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()

if not KEY_ID or not KEY_SECRET:
    print("Missing RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env")
    sys.exit(1)

if not KEY_ID.startswith("rzp_test_"):
    print(f"WARNING: key id does not look like a test-mode key: {KEY_ID[:12]}...")

BASE = "https://api.razorpay.com/v1"
auth = (KEY_ID, KEY_SECRET)


def step(name):
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")


# --- Step 1: verify auth ---
step("1. Verify test-mode authentication")
r = requests.get(f"{BASE}/payments", auth=auth, params={"count": 1})
print("status:", r.status_code)
print("auth works:", r.status_code == 200)
if r.status_code != 200:
    print("response:", r.text)
    sys.exit(1)

# --- Step 2: create a Payment Link ---
step("2. Create Payment Link")
payload = {
    "amount": 4800000,  # paise -> 48,000.00 INR, matches our spec's example case
    "currency": "INR",
    "description": "Recovery case recon-test-1",
    "reference_id": "recon-test-1",
    "customer": {
        "name": "Recon Test Customer",
        "email": "recon-test@example.com",
        "contact": "+918123456780",
    },
    "notify": {"sms": False, "email": False},
    "reminder_enable": False,
}
r = requests.post(f"{BASE}/payment_links", auth=auth, json=payload)
print("status:", r.status_code)
link = r.json()
print(json.dumps(link, indent=2))

if r.status_code not in (200, 201):
    print("Payment Link creation failed.")
    sys.exit(1)

link_id = link["id"]
short_url = link["short_url"]

# --- Step 3: inspect fields available ---
step("3. Fields returned by creation")
print("Available top-level fields:", sorted(link.keys()))

# --- Step 4: fetch it back independently ---
step("4. Fetch Payment Link by id (independent read)")
r = requests.get(f"{BASE}/payment_links/{link_id}", auth=auth)
print("status:", r.status_code)
fetched = r.json()
print(json.dumps(fetched, indent=2))

print(f"\n\n>>> PAYMENT LINK URL TO PAY MANUALLY: {short_url}")
print(f">>> PAYMENT LINK ID: {link_id}")
print(">>> Save this ID - next script will poll/verify against it.")

with open(Path(__file__).resolve().parent / "last_link.json", "w") as f:
    json.dump({"id": link_id, "short_url": short_url}, f, indent=2)

"""
Real Razorpay API wrapper for the runtime system, scoped exactly to what
SPEC.md 11 allows: create Payment Link, fetch Payment Link, resend
notification. Nothing else. Test-mode-only is enforced here too, not just in
the recon scripts - this is the module that actually moves toward money, so
it gets the same hard check.
"""

import os

import requests

BASE = "https://api.razorpay.com/v1"


def _auth() -> tuple[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError(
            f"REFUSING TO RUN: key id is not a test-mode key ({key_id[:12]}...). "
            f"This project must never touch live Razorpay keys or real money."
        )
    return key_id, key_secret


def create_payment_link(
    amount_paise: int,
    description: str,
    reference_id: str,
    customer_name: str,
    customer_email: str,
    customer_contact: str,
) -> dict:
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "reference_id": reference_id,
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "contact": customer_contact,
        },
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
    }
    r = requests.post(f"{BASE}/payment_links", auth=_auth(), json=payload)
    r.raise_for_status()
    return r.json()


def fetch_payment_link(payment_link_id: str) -> dict:
    r = requests.get(f"{BASE}/payment_links/{payment_link_id}", auth=_auth())
    r.raise_for_status()
    return r.json()


def resend_notification(payment_link_id: str, medium: str = "email") -> dict:
    r = requests.post(
        f"{BASE}/payment_links/{payment_link_id}/notify_by/{medium}", auth=_auth()
    )
    r.raise_for_status()
    return r.json()

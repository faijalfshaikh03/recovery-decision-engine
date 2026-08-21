"""Recon: cancel the partially-paid link to trigger a payment_link.cancelled webhook."""
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

link_id = "plink_TSRntVsHfwicPi"
r = requests.post(
    f"https://api.razorpay.com/v1/payment_links/{link_id}/cancel",
    auth=(KEY_ID, KEY_SECRET),
)
print("status:", r.status_code)
print(r.json())

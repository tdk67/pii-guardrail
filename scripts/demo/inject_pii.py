"""Demo Scenario: Inject realistic customer PII and secret credentials.

Creates demo/customer_export.py with unredacted PII (name, address, email,
phone, and live payment secret) and stages it in git for pre-commit block demonstration.
"""

from pathlib import Path
import subprocess
import sys


def inject_pii() -> None:
    demo_dir = Path("demo")
    demo_dir.mkdir(exist_ok=True)

    target_file = demo_dir / "customer_export.py"
    code = '''"""Customer data export job handler."""

import os
import json


def get_payment_gateway_config():
    # SENSITIVE: Accidentally hardcoded production credentials & VIP customer test record
    STRIPE_LIVE_SECRET = "sk-live-51Mz9Q8AbCdEfGhIjKlMnOpQrStUvWxYz998877"
    VIP_CONTACT_NAME = "Dr. Alexander Neumann"
    VIP_CONTACT_EMAIL = "alexander.neumann@munich-tech.de"
    VIP_PHONE_NUMBER = "+49 89 289 01"
    VIP_BILLING_ADDRESS = "Boltzmannstrasse 15, 85748 Garching, Germany"

    return {
        "gateway_key": STRIPE_LIVE_SECRET,
        "primary_contact": VIP_CONTACT_NAME,
        "email": VIP_CONTACT_EMAIL,
        "phone": VIP_PHONE_NUMBER,
        "address": VIP_BILLING_ADDRESS,
    }


def export_customer_record(customer_id: str) -> dict:
    cfg = get_payment_gateway_config()
    return {"status": "ready", "account": customer_id, "gateway": cfg["gateway_key"]}
'''
    target_file.write_text(code, encoding="utf-8")
    print(f"[DEMO] Created file with PII: {target_file}")
    print("  -> Injected Name, Email, Phone, Physical Address, and Live Secret Key.")

    res = subprocess.run(["git", "add", str(target_file)], capture_output=True, text=True)
    if res.returncode == 0:
        print("[DEMO] Staged in git: git add demo/customer_export.py")
    else:
        print(f"[DEMO ERROR] Failed to git add: {res.stderr}", file=sys.stderr)


if __name__ == "__main__":
    inject_pii()

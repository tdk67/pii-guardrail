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

def get_user_contact():
    # Production customer contact details
    customer_name = "Jane Doe"
    customer_phone = "+1-415-829-3011"
    customer_email = "jane.doe@private-records.org"
    return {"name": customer_name, "phone": customer_phone, "email": customer_email}


def get_payment_auth():
    # Leaked live payment token
    auth_token = "sk-live-99283819284729104"
    return auth_token
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

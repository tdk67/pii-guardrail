"""Realistic Git Branch & Merge Simulation for Latch Demo.

Simulates real development by:
1. Creating a base test branch from current main ('demo-test-base')
2. Creating a feature test branch ('demo-test-feature')
3. Developing a realistic 9-file enterprise microservices suite on the feature branch:
   - README.md (architecture documentation additions)
   - src/services/README.md (package architecture breakdown)
   - src/services/billing_engine.py (multi-region VAT, tier pricing, pro-rata upgrades - 75 lines)
   - src/services/notification_dispatcher.py (rate-limited async webhook worker - 37 lines)
   - src/services/rate_limiter.py (token-bucket concurrency limiter - 24 lines)
   - src/services/report_generator.py (markdown summary table formatter - 20 lines)
   - src/services/data_pipeline.py (event batch accumulator and schema normalizer - 22 lines)
   - tests/test_services.py (unit test suite, automatically exempted via path allowlist - 17 lines)
   - src/services/customer_sync.py (sensitive customer PII and live Stripe API secret)
4. Merging the feature branch onto the base branch without committing (--no-commit --no-ff),
   producing a multi-file, multi-chunk realistic staged merge diff (9 files, 225+ lines).
5. Attempting 'git commit' -> Latch pre-commit hook evaluates all chunks and BLOCKS src/services/customer_sync.py!
6. Remediating: replacing hardcoded secrets with os.environ.get(...) and re-staging.
7. Committing cleanly -> Latch evaluates, exempts allowlisted tests, and APPROVES the clean commit!
8. Automatically cleaning up the test branches and returning safely to main.
"""

from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess

BASE_BRANCH = "demo-test-base"
FEATURE_BRANCH = "demo-test-feature"
SERVICES_DIR = Path("src/services")
TESTS_FILE = Path("tests/test_services.py")
README_FILE = Path("README.md")

README_ENTERPRISE_SECTION = """
## Enterprise Microservices Architecture

Latch protects microservice transactions and customer payment ingestion pipelines:
- **Billing Engine**: Automated multi-jurisdiction VAT, tiers, and pro-rata billing
- **Notification Dispatcher**: High-throughput async webhook delivery engine
- **Rate Limiter**: Token-bucket algorithm with thread-safe concurrency locking
- **Report Generator**: Automated markdown summary tables and metric formatting
- **Customer Gateway**: Real-time customer sync with pre-commit PII interception
"""

SERVICES_README_CODE = """# Core Enterprise Services Architecture

This package provides foundational enterprise microservices:
- `billing_engine.py`: Multi-region subscription pricing, seat overages, and VAT calculation.
- `notification_dispatcher.py`: High-throughput async webhook delivery engine.
- `rate_limiter.py`: Concurrency token-bucket rate limiter.
- `report_generator.py`: Markdown summary tables and metric formatting.
- `data_pipeline.py`: Event stream batch accumulator and schema normalization.
- `customer_sync.py`: CRM payment gateway and customer synchronization.
"""

BILLING_ENGINE_CODE = '''"""Multi-region billing and subscription tax calculation engine."""
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SubscriptionTier:
    name: str
    base_price_cents: int
    seats_included: int
    overage_rate_cents: int


TIERS = {
    "starter": SubscriptionTier("Starter", 2900, 5, 500),
    "growth": SubscriptionTier("Growth", 9900, 20, 400),
    "enterprise": SubscriptionTier("Enterprise", 49900, 100, 250),
}


class BillingEngine:
    VAT_RATES: Dict[str, float] = {
        "DE": 0.19,
        "FR": 0.20,
        "GB": 0.20,
        "NL": 0.21,
        "US": 0.08,
    }

    def compute_monthly_invoice(
        self,
        tier_key: str,
        active_seats: int,
        country_code: str = "US",
        discount_pct: float = 0.0,
    ) -> Dict[str, float]:
        tier = TIERS.get(tier_key.lower())
        if not tier:
            raise ValueError(f"Unknown subscription tier: {tier_key}")

        base_cost = tier.base_price_cents / 100.0
        extra_seats = max(0, active_seats - tier.seats_included)
        overage_cost = (extra_seats * tier.overage_rate_cents) / 100.0

        subtotal = base_cost + overage_cost
        discount = subtotal * (discount_pct / 100.0)
        net_amount = subtotal - discount

        vat_rate = self.VAT_RATES.get(country_code.upper(), 0.0)
        tax_amount = round(net_amount * vat_rate, 2)
        total = round(net_amount + tax_amount, 2)

        return {
            "base_cost": base_cost,
            "overage_cost": overage_cost,
            "subtotal": subtotal,
            "discount": discount,
            "tax": tax_amount,
            "total": total,
        }

    def compute_prorated_upgrade(
        self,
        current_tier: str,
        new_tier: str,
        days_remaining_in_cycle: int,
        cycle_total_days: int = 30,
    ) -> float:
        curr = TIERS[current_tier.lower()]
        target = TIERS[new_tier.lower()]
        diff_cents = target.base_price_cents - curr.base_price_cents
        if diff_cents <= 0:
            return 0.0
        ratio = max(0, min(days_remaining_in_cycle, cycle_total_days)) / float(cycle_total_days)
        return round((diff_cents / 100.0) * ratio, 2)
'''

NOTIFICATION_DISPATCHER_CODE = '''"""Rate-limited webhook and asynchronous notification dispatcher."""
import queue
import time
from typing import Callable, Dict, List, Optional


class NotificationDispatcher:
    def __init__(self, max_qsize: int = 1000, rate_limit_per_sec: int = 50):
        self._queue: queue.Queue = queue.Queue(maxsize=max_qsize)
        self.rate_limit_per_sec = rate_limit_per_sec
        self._last_dispatch_ts = 0.0
        self._dispatched_count = 0

    def enqueue(self, destination_url: str, event_name: str, payload: dict) -> bool:
        try:
            self._queue.put_nowait({
                "url": destination_url,
                "event": event_name,
                "payload": payload,
                "queued_at": time.time(),
            })
            return True
        except queue.Full:
            return False

    def drain_batch(self, batch_size: int = 10) -> List[dict]:
        items: List[dict] = []
        while len(items) < batch_size and not self._queue.empty():
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return items

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()
'''

RATE_LIMITER_CODE = '''"""Token-bucket concurrency rate limiter."""
import time
import threading


class TokenBucketLimiter:
    def __init__(self, capacity: int, fill_rate_per_sec: float):
        self.capacity = float(capacity)
        self.fill_rate = fill_rate_per_sec
        self.tokens = float(capacity)
        self.last_update = time.time()
        self._lock = threading.Lock()

    def acquire(self, requested: int = 1) -> bool:
        with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

            if self.tokens >= requested:
                self.tokens -= requested
                return True
            return False
'''

REPORT_GENERATOR_CODE = '''"""Automated performance and metric report generation."""
from typing import Dict, List, Any


def format_summary_table(headers: List[str], rows: List[List[Any]]) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    row_lines = [
        " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(row))
        for row in rows
    ]
    return f"| {header_line} |\n| {separator} |\n" + "\n".join(f"| {r} |" for r in row_lines)
'''

DATA_PIPELINE_CODE = '''"""Event stream batch accumulator and transformation pipeline."""
from typing import Any, Callable, Dict, List


class StreamTransformer:
    def __init__(self, buffer_limit: int = 500):
        self.buffer_limit = buffer_limit
        self._records: List[Dict[str, Any]] = []

    def ingest(self, record: Dict[str, Any]) -> bool:
        if len(self._records) >= self.buffer_limit:
            return False
        normalized = {k.strip().lower(): v for k, v in record.items()}
        self._records.append(normalized)
        return True

    def process_and_flush(self, handler: Callable[[List[Dict[str, Any]]], None]) -> int:
        count = len(self._records)
        if count > 0:
            handler(list(self._records))
            self._records.clear()
        return count
'''

SENSITIVE_CUSTOMER_CODE = '''"""Customer synchronization service."""

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

REMEDIATED_CUSTOMER_CODE = '''"""Customer synchronization service."""
import os

def get_user_contact():
    # Safely loaded from environment variables
    customer_name = os.environ.get("CUSTOMER_NAME", "")
    customer_phone = os.environ.get("CUSTOMER_PHONE", "")
    customer_email = os.environ.get("CUSTOMER_EMAIL", "")
    return {"name": customer_name, "phone": customer_phone, "email": customer_email}


def get_payment_auth():
    # Safely loaded from environment variables
    auth_token = os.environ.get("PAYMENT_AUTH_TOKEN", "")
    return auth_token
'''

TESTS_SERVICES_CODE = '''"""Unit tests for enterprise microservices."""
from src.services.billing_engine import BillingEngine
from src.services.rate_limiter import TokenBucketLimiter


def test_billing_engine():
    engine = BillingEngine()
    invoice = engine.compute_monthly_invoice("growth", 25, country_code="DE")
    assert invoice["base_cost"] == 99.0
    assert invoice["overage_cost"] == 20.0
    assert invoice["tax"] > 0.0


def test_rate_limiter():
    limiter = TokenBucketLimiter(capacity=10, fill_rate_per_sec=10.0)
    assert limiter.acquire(5) is True
    assert limiter.acquire(6) is False
'''


def run_cmd(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def get_current_branch() -> str:
    res = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return res.stdout.strip()


def setup_branches(original_branch: str) -> None:
    print("\n[STEP 1] Preparing branch topology for realistic multi-file PR simulation...")
    print(f"  Base branch:    '{BASE_BRANCH}' (branched from {original_branch})")
    print(f"  Feature branch: '{FEATURE_BRANCH}'")

    # Clean existing test branches if left over
    for b in [BASE_BRANCH, FEATURE_BRANCH]:
        run_cmd(["git", "branch", "-D", b], check=False, capture=True)

    # 1. Create base branch from current main
    run_cmd(["git", "checkout", "-b", BASE_BRANCH, original_branch])

    # 2. Create feature branch from base branch
    run_cmd(["git", "checkout", "-b", FEATURE_BRANCH, BASE_BRANCH])

    # 3. Add realistic multi-file enterprise microservices suite on feature branch
    # Update README
    orig_readme = README_FILE.read_text(encoding="utf-8")
    README_FILE.write_text(orig_readme + README_ENTERPRISE_SECTION, encoding="utf-8")

    # Write service modules
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    (SERVICES_DIR / "README.md").write_text(SERVICES_README_CODE, encoding="utf-8")
    (SERVICES_DIR / "billing_engine.py").write_text(BILLING_ENGINE_CODE, encoding="utf-8")
    (SERVICES_DIR / "notification_dispatcher.py").write_text(NOTIFICATION_DISPATCHER_CODE, encoding="utf-8")
    (SERVICES_DIR / "rate_limiter.py").write_text(RATE_LIMITER_CODE, encoding="utf-8")
    (SERVICES_DIR / "report_generator.py").write_text(REPORT_GENERATOR_CODE, encoding="utf-8")
    (SERVICES_DIR / "data_pipeline.py").write_text(DATA_PIPELINE_CODE, encoding="utf-8")
    (SERVICES_DIR / "customer_sync.py").write_text(SENSITIVE_CUSTOMER_CODE, encoding="utf-8")

    # Write test suite
    TESTS_FILE.write_text(TESTS_SERVICES_CODE, encoding="utf-8")

    run_cmd(["git", "add", "README.md", "src/services", "tests/test_services.py"])
    run_cmd([
        "git",
        "commit",
        "-m",
        "feat(services): add enterprise microservices suite, unit tests, and update docs",
        "--no-verify",
    ])
    print(f"  -> Committed 9-file feature changes on '{FEATURE_BRANCH}'")

    # 4. Switch back to base branch and merge without committing (--no-commit --no-ff)
    run_cmd(["git", "checkout", BASE_BRANCH])
    print(f"\n[STEP 2] Merging '{FEATURE_BRANCH}' into '{BASE_BRANCH}' (--no-commit --no-ff)...")
    merge_res = run_cmd(["git", "merge", "--no-commit", "--no-ff", FEATURE_BRANCH], check=False, capture=True)
    if merge_res.returncode != 0:
        print(f"Merge output:\n{merge_res.stdout}\n{merge_res.stderr}")

    # Show staged diff statistics
    stat = run_cmd(["git", "diff", "--staged", "--stat"], capture=True).stdout
    print(f"\n[DEMO] Staged realistic multi-file, multi-chunk PR diff:\n{stat.strip()}")


def remediate_pii() -> None:
    print(f"\n[STEP 5] Remediating: Replacing hardcoded secrets in {SERVICES_DIR / 'customer_sync.py'} with os.environ...")
    (SERVICES_DIR / "customer_sync.py").write_text(REMEDIATED_CUSTOMER_CODE, encoding="utf-8")
    run_cmd(["git", "add", str(SERVICES_DIR / "customer_sync.py")])
    print("  -> Staged remediated code in git.")


def cleanup_branches(original_branch: str) -> None:
    print(f"\n[CLEANUP] Restoring working tree to original branch '{original_branch}'...")
    run_cmd(["git", "merge", "--abort"], check=False, capture=True)
    run_cmd(["git", "reset", "--hard", "HEAD"], check=False, capture=True)
    run_cmd(["git", "checkout", original_branch], check=False, capture=True)
    for b in [BASE_BRANCH, FEATURE_BRANCH]:
        run_cmd(["git", "branch", "-D", b], check=False, capture=True)
    if SERVICES_DIR.exists():
        shutil.rmtree(SERVICES_DIR, ignore_errors=True)
    if TESTS_FILE.exists():
        TESTS_FILE.unlink(missing_ok=True)
    # Prune unreachable objects created during temporary branch simulation
    run_cmd(["git", "reflog", "expire", "--expire=now", "--all"], check=False, capture=True)
    run_cmd(["git", "gc", "--prune=now"], check=False, capture=True)
    print("[OK] Cleanup complete. Working directory is clean and unreachable demo objects pruned.")


def verify_hook_installed() -> None:
    hook_file = Path(".git/hooks/pre-commit")
    if not hook_file.exists() or "Latch" not in hook_file.read_text(encoding="utf-8", errors="ignore"):
        print("[WARN] Latch pre-commit hook not detected. Installing hook...")
        import sys
        run_cmd([sys.executable, "-m", "latch.cli", "install"])
    else:
        print("[OK] Latch pre-commit hook is verified and active.")


def run_full_simulation() -> None:
    verify_hook_installed()
    orig_branch = get_current_branch()
    print(f"[DEMO START] Current active branch: {orig_branch}")

    try:
        # 1. Setup multi-file branches and merge PR
        setup_branches(orig_branch)

        # 2. Attempt commit -> should be blocked by Latch hook
        print("\n[STEP 3] Running 'git commit' to complete the merge...")
        print("  -> Expected outcome: Latch pre-commit intercepts and BLOCKS src/services/customer_sync.py!")
        commit_res = run_cmd(
            ["git", "commit", "-m", "feat: merge enterprise microservices suite"],
            check=False,
            capture=False,
        )
        if commit_res.returncode != 0:
            print("\n[OK] SUCCESS: Latch correctly BLOCKED the commit containing sensitive data!")
        else:
            print("\n[FAIL] UNEXPECTED: Commit succeeded when it should have been blocked!")

        # 3. Remediation
        remediate_pii()

        # 4. Clean commit -> should succeed
        print("\n[STEP 6] Running 'git commit' after remediation...")
        clean_commit_res = run_cmd(
            ["git", "commit", "-m", "feat: merge clean enterprise microservices suite"],
            check=False,
            capture=False,
        )
        if clean_commit_res.returncode == 0:
            print("\n[OK] SUCCESS: Clean commit was evaluated and ACCEPTED safely by Latch!")
        else:
            print("\n[FAIL] UNEXPECTED: Clean commit failed!")

    finally:
        # 5. Always clean up test branches
        cleanup_branches(orig_branch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulate realistic git branch merge development scenario")
    parser.add_argument("--cleanup-only", action="store_true", help="Only cleanup temporary demo branches")
    args = parser.parse_args()

    orig = get_current_branch()
    if args.cleanup_only:
        cleanup_branches("main" if orig.startswith("demo-") else orig)
    else:
        run_full_simulation()

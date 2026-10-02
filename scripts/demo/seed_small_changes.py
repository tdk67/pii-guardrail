"""Demo Scenario: Seed small clean changes across files.

Creates demo/order_service.py with clean domain logic, stages it in git,
and prepares the environment for a clean commit demo.
"""

from pathlib import Path
import subprocess
import sys


def seed_small_changes() -> None:
    demo_dir = Path("demo")
    demo_dir.mkdir(exist_ok=True)

    order_service_path = demo_dir / "order_service.py"
    code = '''"""Order processing domain service."""

from typing import List, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class OrderItem:
    item_id: str
    quantity: int
    unit_price_cents: int


class OrderService:
    def __init__(self, tax_rate: float = 0.19) -> None:
        self.tax_rate = tax_rate

    def calculate_subtotal(self, items: List[OrderItem]) -> int:
        """Computes subtotal amount in cents."""
        return sum(item.quantity * item.unit_price_cents for item in items)

    def calculate_total_with_tax(self, items: List[OrderItem]) -> int:
        """Returns total order price including standard tax."""
        subtotal = self.calculate_subtotal(items)
        tax = int(subtotal * self.tax_rate)
        return subtotal + tax

    def validate_order(self, order_id: str, items: List[OrderItem]) -> bool:
        """Validates that order has items and positive total."""
        if not items:
            return False
        return self.calculate_subtotal(items) > 0
'''
    order_service_path.write_text(code, encoding="utf-8")
    print(f"[DEMO] Created clean file: {order_service_path} ({len(code.splitlines())} lines)")

    # Stage in git
    res = subprocess.run(["git", "add", str(order_service_path)], capture_output=True, text=True)
    if res.returncode == 0:
        print("[DEMO] Staged in git: git add demo/order_service.py")
    else:
        print(f"[DEMO ERROR] Failed to git add: {res.stderr}", file=sys.stderr)


if __name__ == "__main__":
    seed_small_changes()

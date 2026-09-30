def calculate_total(items: list[dict], tax_rate: float = 0.08) -> float:
    """Calculates order subtotal and adds estimated tax."""
    subtotal = sum(item.get("price", 0.0) * item.get("quantity", 1) for item in items)
    return round(subtotal * (1.0 + tax_rate), 2)


def apply_discount(subtotal: float, discount_percent: float = 0.10) -> float:
    """Applies coupon discount code."""
    discount = subtotal * discount_percent
    return max(0.0, subtotal - discount)

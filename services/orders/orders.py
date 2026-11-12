"""
Mock data-access layer for the AnyCompany Hair Care returns assistant.

Loads order data from a local JSON file at startup and provides functions for
order lookup, return-policy checks, refund status, refund-amount computation,
and applying refunds (idempotent).

Dates are stored relative to "today" (`purchased_days_ago`) and resolved to a
concrete `purchased` date on load. That keeps the demo evergreen: the eligible
order stays inside the 30-day return window no matter when someone clones and
runs this repo.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "mock_data" / "orders.json"

# In-process store, loaded once at import time.
_data: dict = {}


def _resolve_dates(orders: dict) -> None:
    """Resolve each order's relative `purchased_days_ago` into a concrete
    `purchased` ISO date (today - N days), so downstream code can treat
    `purchased` as a normal date string. This is what keeps the demo evergreen.
    An explicit `purchased` value in the JSON, if present, is left as-is.
    """
    today = date.today()
    for order in orders.values():
        if "purchased" not in order and "purchased_days_ago" in order:
            days = order["purchased_days_ago"]
            order["purchased"] = (today - timedelta(days=days)).isoformat()


def _load() -> None:
    """Load the JSON data into memory and resolve relative purchase dates.

    If the ORDERS_BUCKET env var is set (as in the deployed Lambda), the data
    is read from s3://$ORDERS_BUCKET/$ORDERS_KEY (default key: orders.json).
    Otherwise it is read from the local mock data file.

    Note: refunds applied via `apply_refund` live only in this process's
    memory, so they do not persist across Lambda cold starts or instances.
    """
    global _data
    bucket = os.environ.get("ORDERS_BUCKET")
    if bucket:
        import boto3  # available in the Lambda runtime; imported lazily

        key = os.environ.get("ORDERS_KEY", "orders.json")
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"]
        _data = json.load(body)
    else:
        with open(_DATA_PATH, "r") as f:
            _data = json.load(f)
    _resolve_dates(_data.get("orders", {}))


# Load on import so data is available immediately.
_load()

RETURN_WINDOW_DAYS = 30


def get_order(order_number: str) -> dict | None:
    """Return the order dict for the given order number, or None if not found."""
    return _data.get("orders", {}).get(order_number)


def return_policy(order_number: str) -> dict:
    """
    Check whether an order is eligible for a refund.

    Returns a dict with:
      - eligible: bool
      - reason: str explaining why
      - days_since_purchase: int
      - window_days: int (the policy window, always 30)
    """
    order = get_order(order_number)
    if order is None:
        return {
            "eligible": False,
            "reason": "Order not found.",
            "days_since_purchase": 0,
            "window_days": RETURN_WINDOW_DAYS,
        }

    purchased = date.fromisoformat(order["purchased"])
    days_since = (date.today() - purchased).days

    # Already refunded
    if order.get("refund_status") == "refunded":
        return {
            "eligible": False,
            "reason": "This order has already been refunded.",
            "days_since_purchase": days_since,
            "window_days": RETURN_WINDOW_DAYS,
        }

    # Must be delivered to be eligible
    if order.get("status") != "delivered":
        return {
            "eligible": False,
            "reason": f"Order status is '{order.get('status')}'; only delivered orders are eligible.",
            "days_since_purchase": days_since,
            "window_days": RETURN_WINDOW_DAYS,
        }

    # 30-day window
    if days_since > RETURN_WINDOW_DAYS:
        return {
            "eligible": False,
            "reason": f"The 30-day return window has passed ({days_since} days since purchase).",
            "days_since_purchase": days_since,
            "window_days": RETURN_WINDOW_DAYS,
        }

    return {
        "eligible": True,
        "reason": "Order is eligible for a refund.",
        "days_since_purchase": days_since,
        "window_days": RETURN_WINDOW_DAYS,
    }


def refund_status(order_number: str) -> str | None:
    """Return the current refund_status for an order, or None if not found."""
    order = get_order(order_number)
    if order is None:
        return None
    return order.get("refund_status")


def refund_amount(order_number: str) -> float:
    """Compute the total refund amount (sum of price * qty for each line item)."""
    order = get_order(order_number)
    if order is None:
        return 0.0
    return sum(item["price"] * item["qty"] for item in order.get("items", []))


def get_product_inventory(product_code: str) -> dict | None:
    """Return the inventory item for the given product code, or None if not found.

    Returns a dict with:
      - code: str (product code)
      - product_key: str (original slug identifier)
      - name: str (product name)
      - qty: int (quantity in stock)
    """
    return _data.get("inventory", {}).get(product_code)


def apply_refund(order_number: str) -> dict:
    """
    Apply a refund to an order (set refund_status to 'refunded').

    Idempotent: if the order is already refunded, this is a no-op.
    Returns a dict with 'success' and 'message'.
    """
    order = get_order(order_number)
    if order is None:
        return {"success": False, "message": "Order not found."}

    if order.get("refund_status") == "refunded":
        # Idempotent — already refunded, no-op.
        return {"success": True, "message": "Refund already applied (no-op)."}

    # Mutate the in-memory data.
    order["refund_status"] = "refunded"
    return {"success": True, "message": f"Refund applied for order {order_number}."}

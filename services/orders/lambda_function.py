"""
AWS Lambda handler for the orders service, behind an API Gateway HTTP API.

Built with Powertools for AWS Lambda's event handler. Each route delegates to
the matching function in `orders.py`.

Routes:
  GET  /orders/{order_number}                 -> get_order
  GET  /orders/{order_number}/return-policy   -> return_policy
  GET  /orders/{order_number}/refund-status   -> refund_status
  GET  /orders/{order_number}/refund-amount   -> refund_amount
  POST /orders/{order_number}/refund          -> apply_refund
  GET  /inventory/{product_code}              -> get_product_inventory
"""

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from aws_lambda_powertools.utilities.typing import LambdaContext

import orders

logger = Logger()
app = APIGatewayHttpResolver()


def _require_order(order_number: str) -> dict:
    order = orders.get_order(order_number)
    if order is None:
        raise NotFoundError(f"Order {order_number} not found")
    return order


@app.get("/orders/<order_number>")
def get_order(order_number: str):
    return {"order_number": order_number, **_require_order(order_number)}


@app.get("/orders/<order_number>/return-policy")
def return_policy(order_number: str):
    # Unknown orders are reported as ineligible by orders.return_policy itself.
    return orders.return_policy(order_number)


@app.get("/orders/<order_number>/refund-status")
def refund_status(order_number: str):
    _require_order(order_number)
    return {
        "order_number": order_number,
        "refund_status": orders.refund_status(order_number),
    }


@app.get("/orders/<order_number>/refund-amount")
def refund_amount(order_number: str):
    _require_order(order_number)
    return {
        "order_number": order_number,
        "refund_amount": orders.refund_amount(order_number),
    }


@app.post("/orders/<order_number>/refund")
def apply_refund(order_number: str):
    _require_order(order_number)
    return orders.apply_refund(order_number)


@app.get("/inventory/<product_code>")
def get_product_inventory(product_code: str):
    item = orders.get_product_inventory(product_code)
    if item is None:
        raise NotFoundError(f"Product {product_code} not found")
    return item


@logger.inject_lambda_context
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)

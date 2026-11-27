"""
MCP server for the AnyCompany Hair Care customer service agents.

Exposes the orders service and the product information Knowledge Base (v0) as
MCP tools, served over streamable HTTP for AgentCore Runtime.

Configuration (environment variables):
    ORDERS_API_URL   Base URL of the deployed orders API (Terraform output `base_url`).
    RAG_V0_KB_ID     ID of the managed Bedrock Knowledge Base (config.json `rag_v0.kb_id`).
    AWS_REGION       Region for the Bedrock Knowledge Base call (defaults to us-east-1).

The server holds no business logic. Order tools forward to the orders API, and
the search tool forwards to the Bedrock Retrieve API.

Note: `apply_refund` is registered here, but the refunds agent must not bind it.
That exclusion is enforced in the client (`orders_client`), not on this server.
"""

import functools
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import boto3
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

logger = logging.getLogger("mcp_server")
logging.basicConfig(level=logging.INFO, format="%(message)s")

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

_HTTP_TIMEOUT_SECONDS = 10.0
_DEFAULT_TOP_K = 5

_http_client: httpx.Client | None = None
_kb_client: Any = None


def _orders_client() -> httpx.Client:
    """Return the shared HTTP client for the orders API, creating it on first use."""
    global _http_client
    if _http_client is None:
        base_url = os.environ.get("ORDERS_API_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError("ORDERS_API_URL is not set")
        _http_client = httpx.Client(base_url=base_url, timeout=_HTTP_TIMEOUT_SECONDS)
    return _http_client


def _knowledge_base_client() -> Any:
    """Return the shared Bedrock agent runtime client, creating it on first use."""
    global _kb_client
    if _kb_client is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _kb_client = boto3.client("bedrock-agent-runtime", region_name=region)
    return _kb_client


def _call_orders_api(method: str, path: str) -> Any:
    """Send a request to the orders API and return the decoded JSON body.

    Raises ToolError on a 404 (unknown order or product) so the agent sees a
    tool error. Other HTTP failures are raised as ToolError with the status code.
    """
    response = _orders_client().request(method, path)
    if response.status_code == 404:
        raise ToolError(f"Not found: {path}")
    if response.status_code >= 400:
        raise ToolError(f"Orders API returned HTTP {response.status_code} for {method} {path}")
    return response.json()


def _logged(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log each tool call with its name, duration and outcome.

    Matches the observability plan in architecture.md: one structured log line
    per tool call, which feeds per-tool CloudWatch metrics.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        status = "ok"
        try:
            return func(*args, **kwargs)
        except Exception:
            status = "error"
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                '{"tool": "%s", "status": "%s", "duration_ms": %s}',
                func.__name__,
                status,
                duration_ms,
            )

    return wrapper


@mcp.tool()
@_logged
def get_order(order_number: str) -> dict:
    """Get the details of one order, including its line items and purchase date.

    Args:
        order_number: The order number, as the customer gives it (for example "AC-1001").

    Returns:
        The order record from the orders service: line items, purchase date and refund fields.

    Raises:
        ToolError: If no order has this number.
    """
    return _call_orders_api("GET", f"/orders/{order_number}")


@mcp.tool()
@_logged
def return_policy(order_number: str) -> dict:
    """Check whether an order is eligible for a refund under the 30-day return policy.

    Use this before any refund discussion. An unknown order is not an error. It
    returns eligible=false with the reason "Order not found.".

    Args:
        order_number: The order number, as the customer gives it.

    Returns:
        A dict with `eligible` (bool) and `reason` (str).
    """
    return _call_orders_api("GET", f"/orders/{order_number}/return-policy")


@mcp.tool()
@_logged
def refund_status(order_number: str) -> dict:
    """Get the refund status of an order (for example "refunded", or no refund yet).

    Args:
        order_number: The order number, as the customer gives it.

    Returns:
        A dict with `order_number` and `refund_status` (a string, or null when
        the order has no refund).

    Raises:
        ToolError: If no order has this number.
    """
    return _call_orders_api("GET", f"/orders/{order_number}/refund-status")


@mcp.tool()
@_logged
def refund_amount(order_number: str) -> dict:
    """Compute the amount that would be refunded for an order (sum of price times quantity over its items).

    This computes the amount only. It does not issue a refund.

    Args:
        order_number: The order number, as the customer gives it.

    Returns:
        A dict with `order_number` and `refund_amount` (a number).

    Raises:
        ToolError: If no order has this number.
    """
    return _call_orders_api("GET", f"/orders/{order_number}/refund-amount")


@mcp.tool()
@_logged
def apply_refund(order_number: str) -> dict:
    """Mark an order as refunded.

    Not for agent use. The refunds agent must not call this tool. A human
    approves refunds outside this service. The change is held in memory only
    and is not durable across instances.

    Args:
        order_number: The order number to mark as refunded.

    Returns:
        A dict with `success` (bool) and `message` (str). Refunding an
        already-refunded order is a no-op that returns success.

    Raises:
        ToolError: If no order has this number.
    """
    return _call_orders_api("POST", f"/orders/{order_number}/refund")


@mcp.tool()
@_logged
def get_product_inventory(product_code: str) -> dict:
    """Get the current inventory for a product.

    No agent uses this tool yet. Inventory questions are out of scope for the
    product questions component (see docs/adr/rag_system.md).

    Args:
        product_code: The product code (SKU).

    Returns:
        The inventory record for the product: code, product key, name and quantity in stock.

    Raises:
        ToolError: If no product has this code.
    """
    return _call_orders_api("GET", f"/inventory/{product_code}")


@mcp.tool()
@_logged
def search_product_information(query: str, top_k: int = _DEFAULT_TOP_K) -> dict:
    """Search the product information knowledge base (product pages, FAQ and hair-type guide).

    Use this to answer product questions. Each result gives the passage text and
    the source document it came from, so answers can cite their source.

    Args:
        query: The customer's question, in natural language.
        top_k: The number of passages to return. Defaults to 5.

    Returns:
        A dict with `results`: a list of items, each with `passage` (text),
        `source` (the document key in the knowledge base) and `score` (relevance).
    """
    if top_k < 1:
        raise ToolError(f"top_k must be at least 1, got: {top_k}")

    kb_id = os.environ.get("RAG_V0_KB_ID", "")
    if not kb_id:
        raise ToolError("RAG_V0_KB_ID is not set")

    response = _knowledge_base_client().retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            # The v0 KB is a managed knowledge base, which takes managedSearchConfiguration.
            # vectorSearchConfiguration is rejected for managed KBs.
            "managedSearchConfiguration": {"numberOfResults": top_k},
        },
    )

    results = []
    for item in response.get("retrievalResults", []):
        location = item.get("location", {}).get("s3Location", {})
        results.append(
            {
                "passage": item.get("content", {}).get("text", ""),
                "source": location.get("uri", ""),
                "score": item.get("score"),
            }
        )
    return {"results": results}


def main():
    """Start the MCP server on streamable HTTP."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

"""
Thin client for the orders service, through the MCP server.

Exposes only the read-only order tools the refunds agent may use: get_order,
return_policy, refund_status and refund_amount. The MCP server also registers
`apply_refund`, but this client deliberately has no method for it: the refunds
agent never issues refunds, a human does (see docs/adr/agent_graph.md).
"""

import logging
from typing import Any

from mcp_client import McpClient, McpClientError, McpToolError

logger = logging.getLogger("agents.orders_client")


class OrdersClientError(Exception):
    """An orders tool call failed (endpoint, transport or tool error)."""


class OrderNotFoundError(OrdersClientError):
    """No order has this number."""


class OrdersClient:
    """Read order data through the MCP server's orders tools."""

    def __init__(self, *, region: str, runtime_arn: str = "", url: str = ""):
        self._mcp = McpClient(region=region, runtime_arn=runtime_arn, url=url)

    @property
    def url(self) -> str:
        return self._mcp.url

    def _call(self, tool: str, order_number: str) -> dict[str, Any]:
        try:
            payload = self._mcp.call_tool(tool, {"order_number": order_number})
        except McpToolError as exc:
            if "not found" in str(exc).lower():
                raise OrderNotFoundError(f"Order {order_number} not found") from exc
            raise OrdersClientError(str(exc)) from exc
        except McpClientError as exc:
            raise OrdersClientError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise OrdersClientError(f"Unexpected {tool} output: {payload!r}")
        return payload

    def get_order(self, order_number: str) -> dict[str, Any]:
        """Order details: items, status, purchase date, refund status."""
        return self._call("get_order", order_number)

    def return_policy(self, order_number: str) -> dict[str, Any]:
        """Eligibility under the 30-day policy: eligible, reason, days_since_purchase."""
        return self._call("return_policy", order_number)

    def refund_status(self, order_number: str) -> dict[str, Any]:
        """The order's refund status (None when no refund has been made)."""
        return self._call("refund_status", order_number)

    def refund_amount(self, order_number: str) -> dict[str, Any]:
        """The amount a refund of the order would be."""
        return self._call("refund_amount", order_number)

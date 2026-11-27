"""
Thin client for the product information knowledge base, through the MCP server.

The agents never call AWS services for retrieval directly. This client calls the
MCP server's `search_product_information` tool and returns its passages, so the
product questions node can be tested with a fake client.

The endpoint (local `url`, or `runtime_arn` on AgentCore Runtime) and the
transport are handled by mcp_client.py.
"""

import logging
from typing import TypedDict

from mcp_client import McpClient, McpClientError, agentcore_mcp_url

__all__ = ["Passage", "RagClient", "RagClientError", "agentcore_mcp_url"]

logger = logging.getLogger("agents.rag_client")

SEARCH_TOOL = "search_product_information"


class Passage(TypedDict):
    passage: str
    source: str  # s3 URI of the source document in the knowledge base
    score: float | None


class RagClientError(Exception):
    """The knowledge base search failed (endpoint, transport or tool error)."""


class RagClient:
    """Search the product information knowledge base through the MCP server."""

    def __init__(self, *, region: str, runtime_arn: str = "", url: str = ""):
        self._mcp = McpClient(region=region, runtime_arn=runtime_arn, url=url)

    @property
    def url(self) -> str:
        return self._mcp.url

    @property
    def signed(self) -> bool:
        return self._mcp.signed

    def search(self, query: str, top_k: int) -> list[Passage]:
        """Return up to `top_k` passages for the query. Raises RagClientError on failure."""
        try:
            payload = self._mcp.call_tool(SEARCH_TOOL, {"query": query, "top_k": top_k})
        except McpClientError as exc:
            raise RagClientError(str(exc)) from exc
        if not isinstance(payload, dict):
            raise RagClientError(f"Unexpected {SEARCH_TOOL} output: {payload!r}")
        return [
            Passage(
                passage=str(item.get("passage", "")),
                source=str(item.get("source", "")),
                score=item.get("score"),
            )
            for item in payload.get("results", [])
        ]

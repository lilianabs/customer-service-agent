"""
Thin client for the product information knowledge base, through the MCP server.

The agents never call AWS services for retrieval directly. This client calls the
MCP server's `search_product_information` tool and returns its passages, so the
product questions node can be tested with a fake client.

Endpoint, in order of precedence:
  - `url`: a plain MCP URL, unsigned. For a local server started with
    `uv run python services/mcp-server/server.py` (http://localhost:8000/mcp).
  - `runtime_arn`: the MCP server on AgentCore Runtime. Requests are signed with
    SigV4 (IAM inbound auth, the same auth `agentcore invoke` uses).
"""

import asyncio
import json
import logging
from typing import Any, TypedDict
from urllib.parse import quote

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("agents.rag_client")

SEARCH_TOOL = "search_product_information"
_TIMEOUT_SECONDS = 30


class Passage(TypedDict):
    passage: str
    source: str  # s3 URI of the source document in the knowledge base
    score: float | None


class RagClientError(Exception):
    """The knowledge base search failed (endpoint, transport or tool error)."""


class _SigV4Auth(httpx.Auth):
    """Sign each request with SigV4 for the AgentCore Runtime endpoint."""

    requires_request_body = True

    def __init__(self, region: str, service: str = "bedrock-agentcore"):
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RagClientError("No AWS credentials found to sign MCP requests")
        self._credentials = credentials
        self._region = region
        self._service = service

    def auth_flow(self, request: httpx.Request):
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers={k: v for k, v in request.headers.items() if k.lower() != "connection"},
        )
        SigV4Auth(self._credentials.get_frozen_credentials(), self._service, self._region).add_auth(
            aws_request
        )
        request.headers.update(dict(aws_request.headers.items()))
        yield request


def agentcore_mcp_url(runtime_arn: str, region: str) -> str:
    """Build the MCP invocation URL for a runtime on AgentCore Runtime."""
    encoded_arn = quote(runtime_arn, safe="")
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}"
        "/invocations?qualifier=DEFAULT"
    )


def _leaf_exceptions(exc: BaseException) -> list[BaseException]:
    """Flatten the ExceptionGroups that the MCP client's task groups raise."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for sub in exc.exceptions for leaf in _leaf_exceptions(sub)]
    return [exc]


def _parse_results(result: Any) -> list[Passage]:
    """Read the passages from a call_tool result (structured content, or JSON text)."""
    payload = result.structuredContent
    if not payload:
        texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        try:
            payload = json.loads(texts[0]) if texts else {}
        except json.JSONDecodeError as exc:
            raise RagClientError(f"Unexpected {SEARCH_TOOL} output: {texts[0]!r}") from exc
    return [
        Passage(
            passage=str(item.get("passage", "")),
            source=str(item.get("source", "")),
            score=item.get("score"),
        )
        for item in payload.get("results", [])
    ]


class RagClient:
    """Search the product information knowledge base through the MCP server."""

    def __init__(self, *, region: str, runtime_arn: str = "", url: str = ""):
        if url:
            self.url = url
            self.signed = False
        elif runtime_arn:
            self.url = agentcore_mcp_url(runtime_arn, region)
            self.signed = True
        else:
            self.url = ""
            self.signed = False
        self.region = region

    def search(self, query: str, top_k: int) -> list[Passage]:
        """Return up to `top_k` passages for the query. Raises RagClientError on failure."""
        if not self.url:
            raise RagClientError("No MCP endpoint configured (mcp.url or mcp.runtime_arn)")
        try:
            return asyncio.run(self._search(query, top_k))
        except Exception as exc:
            causes = _leaf_exceptions(exc)
            if len(causes) == 1 and isinstance(causes[0], RagClientError):
                raise causes[0] from exc
            detail = "; ".join(repr(c) for c in causes)
            raise RagClientError(f"{SEARCH_TOOL} call to {self.url} failed: {detail}") from exc

    async def _search(self, query: str, top_k: int) -> list[Passage]:
        auth = _SigV4Auth(self.region) if self.signed else None
        transport = streamablehttp_client(self.url, auth=auth, timeout=_TIMEOUT_SECONDS)
        async with transport as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(SEARCH_TOOL, {"query": query, "top_k": top_k})
        if result.isError:
            texts = [getattr(c, "text", "") for c in result.content]
            raise RagClientError(f"{SEARCH_TOOL} returned an error: {' '.join(texts)}")
        return _parse_results(result)

"""
Shared MCP plumbing for the agents' thin clients (rag_client, orders_client).

Calls one tool on the MCP server over streamable HTTP and returns its decoded
output. Endpoint, in order of precedence:
  - `url`: a plain MCP URL, unsigned. For a local server started with
    `uv run python services/mcp-server/server.py` (http://localhost:8000/mcp).
  - `runtime_arn`: the MCP server on AgentCore Runtime. Requests are signed with
    SigV4 (IAM inbound auth, the same auth `agentcore invoke` uses).

Each call opens its own MCP session, so the clients stay synchronous and
stateless.
"""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger("agents.mcp_client")

_TIMEOUT_SECONDS = 30


class McpClientError(Exception):
    """The MCP call failed (no endpoint, transport error or unreadable output)."""


class McpToolError(McpClientError):
    """The tool ran and returned an error (for example, an unknown order)."""


class _SigV4Auth(httpx.Auth):
    """Sign each request with SigV4 for the AgentCore Runtime endpoint."""

    requires_request_body = True

    def __init__(self, region: str, service: str = "bedrock-agentcore"):
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise McpClientError("No AWS credentials found to sign MCP requests")
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


def _texts(result: Any) -> list[str]:
    return [c.text for c in result.content if getattr(c, "type", "") == "text"]


def parse_tool_result(name: str, result: Any) -> Any:
    """Decode a call_tool result: structured content, or JSON in the first text item.

    FastMCP wraps non-dict outputs as {"result": value}; that wrapper is removed.
    Raises McpToolError when the tool reported an error.
    """
    if result.isError:
        raise McpToolError(" ".join(_texts(result)) or f"{name} returned an error")
    payload = result.structuredContent
    if payload is None:
        texts = _texts(result)
        if not texts:
            return None
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError as exc:
            raise McpClientError(f"Unexpected {name} output: {texts[0]!r}") from exc
    if isinstance(payload, dict) and set(payload) == {"result"}:
        return payload["result"]
    return payload


class McpClient:
    """Call tools on the MCP server."""

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

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call one tool and return its decoded output.

        Raises McpToolError if the tool reports an error, McpClientError otherwise.
        """
        if not self.url:
            raise McpClientError("No MCP endpoint configured (mcp.url or mcp.runtime_arn)")
        try:
            return asyncio.run(self._call(name, arguments))
        except Exception as exc:
            causes = _leaf_exceptions(exc)
            if len(causes) == 1 and isinstance(causes[0], McpClientError):
                raise causes[0] from exc
            detail = "; ".join(repr(c) for c in causes)
            raise McpClientError(f"{name} call to {self.url} failed: {detail}") from exc

    async def _call(self, name: str, arguments: dict[str, Any]) -> Any:
        auth = _SigV4Auth(self.region) if self.signed else None
        transport = streamablehttp_client(self.url, auth=auth, timeout=_TIMEOUT_SECONDS)
        async with transport as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
        return parse_tool_result(name, result)

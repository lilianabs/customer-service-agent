# ADR: MCP server architecture

- **Status:** Accepted
- **Date:** 2026-11-23
- **Related:** [Architecture](../architecture.md), [Implementation plan](../implementation_plan.md) (Day 4), [Orders service ADR](orders_service.md), [Product information RAG ADR](rag_system.md)

## Context

The agents must not call AWS services directly. Architecture requires that they reach the product information KB and the orders service through an MCP server that exposes them as tools (see [architecture.md](../architecture.md), "Agents" and the system diagram). The thin clients (`rag_client`, `orders_client`) then call those tools, so agent logic stays testable with mocks.

Two existing decisions shape the server:

- The orders service is a deployed HTTP API (see [orders_service.md](orders_service.md)). `apply_refund` only changes an in-memory copy and is not durable.
- The product information KB has three variants (see [rag_system.md](rag_system.md)). Only v0, the managed Bedrock Knowledge Base, is built so far.

The refunds agent must not issue refunds. It gathers order details, checks eligibility and hands a case summary to a human (see [architecture.md](../architecture.md), "Agents").

The MCP server is the Day 4 deliverable. Its current code in `services/mcp-server/server.py` is the AgentCore starter scaffold: a single `roll_d20` tool on `FastMCP` with `stateless_http=True`, served over `streamable-http`. That scaffold will be replaced.

## Decision

### Overview

```
agents (orders_client, rag_client) -> MCP server (AgentCore Runtime, streamable HTTP)
    -> orders API: API Gateway (orders-api, stage v1) -> Lambda -> S3
    -> product information KB: Bedrock Knowledge Base v0 (Retrieve API)
```

- The MCP server is a Python service built on `FastMCP` from the `mcp` package. It keeps the scaffold's settings: `stateless_http=True`, `streamable-http` transport.
- It is deployed to Amazon Bedrock AgentCore Runtime, as the scaffold's `bedrock-agentcore` dependencies imply.
- It has no business logic. Each tool calls one backend and returns its result.

### Tools

| Tool | Backend call | Notes |
| --- | --- | --- |
| `get_order(order_number)` | `GET /orders/{order_number}` | Unknown order: tool error (404). |
| `return_policy(order_number)` | `GET /orders/{order_number}/return-policy` | Unknown order returns `eligible: false`, reason "Order not found.", as the API does. |
| `refund_status(order_number)` | `GET /orders/{order_number}/refund-status` | Unknown order: tool error (404). |
| `refund_amount(order_number)` | `GET /orders/{order_number}/refund-amount` | Unknown order: tool error (404). |
| `apply_refund(order_number)` | `POST /orders/{order_number}/refund` | Registered on the server. Not in the agents' tool list (see below). |
| `get_product_inventory(product_code)` | `GET /inventory/{product_code}` | Registered on the server. No agent calls it for now (see [rag_system.md](rag_system.md)). |
| `search_product_information(query, top_k=5)` | Bedrock `retrieve` on the v0 Knowledge Base | Returns passages with their source document IDs. `top_k` matches the v0 baseline. |

The tool names mirror the orders service's function names, so the ADR, the orders code and the tool list use the same words.

### Calling the orders service

- The server calls the deployed API Gateway URL over HTTP. It does not import `services/orders/`. This keeps one data path for the orders service, the same path `orders_client` uses.
- The base URL comes from an environment variable set by Terraform from the `orders` module output.
- Responses are returned as the API returns them. The server does not reshape the data.
- HTTP 404 from the API becomes an MCP tool error, except for `return_policy`, which returns the API's 200 result.

### Refund tool exposure

`apply_refund` is registered on the MCP server, because all six orders functions are exposed. It is left out of the agent-facing tool list, which is the set of tools `orders_client` binds for the refunds agent. The refunds agent therefore sees only the read tools (`get_order`, `return_policy`, `refund_status`, `refund_amount`).

This exclusion is made in the client, not on the server. Any MCP client that lists the server's tools can still see and call `apply_refund`. The exclusion is a control on the agents, not a security boundary (see Consequences).

### Knowledge Base search

- `search_product_information` calls the Bedrock `retrieve` API on the v0 managed Knowledge Base. The KB ID comes from `config.json` (`rag_v0.kb_id`) through an environment variable.
- The server fixes the variant to v0. There is no `KB_VARIANT` switch yet. The retriever sits behind the `Retriever` interface from [rag_system.md](rag_system.md), so v1 and v2 can be added later without changing tool names or the tool's inputs.
- The result is a list of passages, each with its source document ID.

### Hosting and authentication

- The server runs on AgentCore Runtime.
- There is no authentication, as decided for this demo. This is consistent with the orders service ADR, where the data is mock data and the deployment is short-lived.

### Observability

Per the observability table in [architecture.md](../architecture.md), the server emits structured logs for each tool call with the tool name, duration and error. These feed CloudWatch metrics per tool.

### Repository changes

- Replace the `roll_d20` scaffold tool in `services/mcp-server/server.py` with the tools above.
- Add the two backend settings (orders API URL, KB ID) as environment variables set by Terraform.
- Tests use mocked backends, as the architecture requires for agent and client tests.

## Alternatives considered

- **Import the orders code directly into the MCP server.** This avoids the HTTP hop, but it creates a second data path that can drift from the deployed API. Rejected.
- **Leave `apply_refund` off the server entirely.** This is the strongest guard against an agent refunding an order, but it removes the endpoint that the orders ADR says exists so the agent flow can be exercised end to end. Rejected. The client-side exclusion is used instead.
- **One generic tool, such as `call_orders_api(route, args)`.** This is smaller, but agents would have to know the routes, and the tool descriptions would not guide them. Rejected.
- **Expose a document fetch tool for the KB.** Not needed for the baseline. The search result already carries the passage and its source. Deferred.

## Consequences

- **Good:** the agents reach both backends through one interface, and the orders data path is the same one the deployed API uses.
- **Good:** adding KB variants later does not change tool names or the agents' code.
- **Limitation:** `apply_refund` is reachable by any client of the MCP server. Keeping it out of the agents' tool list is a convention enforced in the client. It is not access control. Any future deployment that exposes the server beyond this demo needs authentication and a server-side restriction on `apply_refund`.
- **Limitation:** there is no authentication on the server, so anyone with the URL can call every tool, including `apply_refund`. This is acceptable only because the data is mock data and the deployment is short-lived.
- **Limitation:** refunds applied through the server are not durable, for the reasons given in [orders_service.md](orders_service.md). Agent evaluations must not depend on a refund showing up in a later call.
- **Limitation:** the server is v0-only. Comparing KB variants requires adding the variant switch and re-running the eval set.

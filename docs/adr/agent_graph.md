# ADR: Agent graph architecture (LangGraph)

- **Status:** Proposed
- **Date:** 2026-11-25
- **Related:** [Architecture](../architecture.md), [Implementation plan](../implementation_plan.md) (Day 5), [MCP server ADR](mcp_server.md), [Product information RAG ADR](rag_system.md), [Orders service ADR](orders_service.md)

## Context

The system has three agents, built as one LangGraph graph that runs on Amazon Bedrock AgentCore (see [architecture.md](../architecture.md), "Agents"):

- the intent router, which classifies the user's message and hands off;
- the product questions component, which is either v0 (a simple RAG workflow) or v1 (agentic RAG), chosen by experiment;
- the refunds agent, which checks the order and the return policy, then escalates to a human.

Agents reach the product information KB and the orders service only through `rag_client` and `orders_client`, which call the MCP server's tools ([MCP server ADR](mcp_server.md)). The refunds agent does not issue refunds. It hands a case summary to a human for approval.

Input and output guardrails apply to every conversation: input checks for PII and prompt injection, and output validates each response before it reaches the user. Cost limits (max request length, max tokens, `recursion_limit`) also apply.

## Decision

### Graph shape

```
user message
  -> input guardrail (PII, prompt injection)
  -> intent router --(conditional edge on intent)--> product questions (v0 or v1, from config)
                   \--> refunds agent --> escalation (case summary for a human)
  -> output guardrail (response validation)
  -> reply to the user
```

- **Guardrails are graph nodes.** The input guardrail is the first node and the output guardrail is the last one, so every path passes through both. Both are implemented with Amazon Bedrock Guardrails: the input guardrail checks for PII and prompt injection, and the output guardrail validates the response.
- **Intent router:** no tools. It returns an intent label, and a conditional edge picks the next node. There are no agent-to-agent handoffs, so the router is the only place that decides where a message goes.
- **Product questions:** one node in the graph. The approach (v0 or v1) is selected by config, so either approach runs in the same graph shape against any KB variant. The v1 (agentic RAG) approach loops between the model and retrieval; it is bounded only by `recursion_limit` (see Limits).
- **Refunds agent:** calls the read-only orders tools (`get_order`, `return_policy`, `refund_status`, `refund_amount`), checks eligibility, and writes a case summary to the escalation node. The escalation node is terminal in the graph. A human reviews the case outside the graph, so the graph does not pause for approval.
- **Turn:** each user message is one graph run. The graph ends after the reply. The next message starts a new run at the intent router, with the conversation state restored from the checkpointer.

### Reply to the user after escalation

The refunds agent's reply explains the policy result: whether the order is eligible under the return policy, and that a human will decide the refund. The agent does not approve or deny the refund itself.

### State and memory

- **Short-term memory:** the full message list is part of the graph state and is passed to every node.
- **Checkpointer:** the state is saved between turns with the AgentCore Memory service, keyed by conversation ID.
- **Long-term memory:** not decided in this ADR. It is a first version only if time allows on Day 5 (see [implementation plan](../implementation_plan.md)).

### Limits

- **Agentic RAG loop:** there is no separate retrieval cap. `recursion_limit` is the only limit on how many times the product questions loop can run.
- **Max request length and max tokens per call:** set per agent and enforced at invocation time. Their values are not decided in this ADR (see [architecture.md](../architecture.md), "Guardrails").

### Models

Each graph node uses its own model.

| Node | Model |
| --- | --- |
| Intent router | Amazon Nova Lite |
| Product questions (v0 or v1) | Claude Sonnet 5.5 |
| Refunds agent | Claude Sonnet 5.5 |

## Consequences

**Positive**

- One graph shape serves both product questions approaches, so the comparison changes only the approach, not the wiring.
- Both guardrails sit in the graph, so no path can skip them.
- The refunds agent is read-only, and the human reviewer stays the only one who approves refunds.
- The router uses a small, fast model, so the cost of each turn is mostly the answering or refund agent.

**Negative**

- Two guardrail nodes add latency to every turn.
- Because the graph does not pause for approval, the refund outcome is not known inside the conversation. The user is told that a human will decide.
- `recursion_limit` is the only bound on the agentic RAG loop, so one question can use many tokens before it stops. Max tokens per call limits each call, but not the total.
- Three different models mean three settings to keep in sync with the evaluations.

## Open questions

- Exact values for `recursion_limit`, max request length and max tokens per call.
- The Bedrock model ID for Amazon Nova Lite, to confirm before deployment.

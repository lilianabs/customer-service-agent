# ADR: Agent graph architecture (LangGraph)

- **Status:** Proposed
- **Date:** 2026-11-25
- **Related:** [Architecture](../architecture.md), [Implementation plan](../implementation_plan.md) (Day 5), [MCP server ADR](mcp_server.md), [Product information RAG ADR](rag_system.md), [Orders service ADR](orders_service.md)

## Context

The system has three agents, built as one LangGraph graph that runs on Amazon Bedrock AgentCore (see [architecture.md](../architecture.md), "Agents"):

- the intent router, which classifies the user's message and hands off;
- the product questions component, which is either v0 (a simple RAG workflow) or v1 (agentic RAG), chosen by experiment;
- the refunds agent, which answers order questions and, for refund requests, checks the order and the return policy, then escalates to a human.

Agents reach the product information KB and the orders service only through `rag_client` and `orders_client`, which call the MCP server's tools ([MCP server ADR](mcp_server.md)). The refunds agent does not issue refunds. It hands a case summary to a human for approval.

Users do not always write about products or refunds. A message can be off-topic, and a single message can contain both a product question and a refund request. The graph must handle both cases.

Input and output guardrails apply to every conversation: input checks for PII and prompt injection, and output validates each response before it reaches the user. Cost limits (max request length, max tokens, `recursion_limit`) also apply.

## Decision

### Graph shape

```
user message
  -> input guardrail (PII, prompt injection)
  -> intent router: returns one or more of product, refund, other
       product -> product questions (v0 or v1, from config)
       refund  -> refunds agent -> escalation (only for eligible refund requests)
       other   -> general node: limited general answer (fixed reply as fallback)
       (both product and refund: run both, in the order they appear in the message)
  -> output guardrail (response validation)
  -> reply to the user
```

- **Guardrails are graph nodes.** The input guardrail is the first node and the output guardrail is the last one, so every path passes through both. Both are implemented with Amazon Bedrock Guardrails: the input guardrail checks for PII and prompt injection, and the output guardrail validates the response.
- **Intent router:** no tools. It returns one or more intent labels: `product`, `refund`, or `other`. A conditional edge sends the message to the matching node. There are no agent-to-agent handoffs, so the router is the only place that decides where a message goes.
- **Product questions:** one node in the graph. The approach (v0 or v1) is selected by config, so either approach runs in the same graph shape against any KB variant. The v1 (agentic RAG) approach loops between the model and retrieval; it is bounded only by `recursion_limit` (see Limits).
- **Refunds agent:** answers two kinds of request.
  - *Order status questions* ("where is my order?", "has my refund been processed?") are answered from the read-only orders tools (`get_order`, `refund_status`). No escalation.
  - *Refund requests* also use `return_policy` and `refund_amount` and check eligibility. Only eligible requests are escalated: the model calls an `escalate_to_human` tool, which re-checks `return_policy` in code and refuses an ineligible order, so eligibility does not depend on the model. The tool builds a case summary (order number, items, purchase date, refund amount, policy reason, one-sentence request summary; no customer name or email), and the escalation node hands it to a human. For now that means one structured log line (`refund_escalation`, CloudWatch) and the case in the turn's response. A human reviews the case outside the graph, so the graph does not pause for approval. The escalation node is not terminal: a following intent in the same message still runs.
  - *How it runs:* Claude with the four read-only order tools plus `escalate_to_human`, looping until it answers. The loop runs inside the refunds node on a local message list, so tool calls and tool results stay out of the shared conversation history. It is bounded by `refunds_max_tool_rounds` (config). `apply_refund` is not exposed: `orders_client` has no method for it.
- **Turn:** each user message is one graph run. The graph ends after the reply. The next message starts a new run at the intent router, with the conversation state restored from the checkpointer.

### Messages that are neither product nor refund (`other`)

The router returns `other` for messages outside the product information and refunds scope. The `other` branch is the general node: one model call with no tools and a system prompt that keeps it on scope. It replies briefly to greetings and thanks, gives short general hair care answers without naming products, politely declines anything else, and always says what the assistant can help with (product questions and refund or order requests). It must not state facts about the company (policies, prices, stock, hours, contact details) or claim to take actions. If the model call fails or returns nothing, the node returns a fixed reply instead. The fixed reply's wording is an open question.

- The off-topic exchange stays in the conversation's message history, so follow-up messages have context.
- The reply is produced by a node in the graph, so it passes through the output guardrail like every other reply.

Other ways to handle this were considered and not chosen for the first version (see Alternatives considered).

### Messages with both a product question and a refund request

The router can return both `product` and `refund`. The graph then runs both branches, one after the other, in the order the intents appear in the user's message. Their replies are combined into one reply to the user.

- Each branch has its own reply, so the user sees both answers in one turn.
- If the refund branch escalates, the case summary is still written, and the reply says a human will decide the refund.

### Reply to the user after escalation

The refunds agent's reply explains the policy result: whether the order is eligible under the return policy, and that a human will decide the refund. The agent does not approve or deny the refund itself.

### State and memory

- **Short-term memory:** the full message list is part of the graph state and is passed to every node. This includes the off-topic turns.
- **Checkpointer:** the state is saved between turns with the AgentCore Memory service, keyed by conversation ID.
- **Long-term memory:** not decided in this ADR. It is a first version only if time allows on Day 5 (see [implementation plan](../implementation_plan.md)).

### Limits

- **Agentic RAG loop:** there is no separate retrieval cap. `recursion_limit` is the only limit on how many times the product questions loop can run.
- **Max request length and max tokens per call:** set per agent and enforced at invocation time. Their values are not decided in this ADR (see [architecture.md](../architecture.md), "Guardrails").

### Models

Each graph node uses its own model.

| Node | Model | Model ID |
| --- | --- | --- |
| Intent router | Amazon Nova Micro | `amazon.nova-micro-v1:0` |
| Product questions (v0 or v1) | Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` |
| Refunds agent | Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` |
| General (`other`) | Amazon Nova Micro | `amazon.nova-micro-v1:0` |

## Alternatives considered

These options were considered for messages outside the scope. The first was chosen on 2026-11-25 and replaced by the second on 2026-11-27; the others are recorded in case the general answer is not enough later.

**Off-topic messages**

1. **Fixed out-of-scope reply (first choice, now the fallback).** Cheap, predictable and easy to test. The downside is that it can't answer a general question.
2. **Limited general answer (chosen 2026-11-27).** A model call with no tools and a system prompt that keeps it on hair care and the company. It feels friendlier, but it can drift off-topic or make claims about the company that aren't true. It needs its own evaluation cases.
3. **Clarify first.** When the router is unsure, a node asks the user one question ("Are you asking about a product or a refund?") before routing. This also covers ambiguous messages, but it adds a turn and needs a rule for when the router is unsure, such as a confidence threshold. Not chosen for the first version.
4. **Escalate to a human.** Anything the router can't place goes to the human reviewer. This is the safest for a support team, but it adds load to the reviewer for messages that have nothing to do with refunds.

**Order status questions**

- **Chosen:** handled by the refunds agent, which already has the order tools. These questions need no escalation.
- **Not chosen:** a separate order-status label and agent. This would duplicate the order tools and add a fourth node.

**Messages with both product and refund intents**

- **Chosen:** the router returns both labels, and both branches run in the order they appear in the message.
- **Not chosen:** the router picks one intent and ignores the other. This would drop part of the user's request.

## Consequences

**Positive**

- One graph shape serves both product questions approaches, so the comparison changes only the approach, not the wiring.
- Both guardrails sit in the graph, so no path can skip them.
- The refunds agent is read-only, and the human reviewer stays the only one who approves refunds.
- Off-topic messages get a short, friendly answer from a small, cheap model, with a fixed reply as fallback if the call fails.
- Order status questions are answered without escalation, which keeps the reviewer's queue for refund requests.
- The router uses a small, fast model, so the cost of each turn is mostly the answering or refund agent.

**Negative**

- Two guardrail nodes add latency to every turn.
- A message with both intents runs two branches, so it costs and takes about twice as long as a single-intent message.
- Because the graph does not pause for approval, the refund outcome is not known inside the conversation. The user is told that a human will decide.
- `recursion_limit` is the only bound on the agentic RAG loop, so one question can use many tokens before it stops. Max tokens per call limits each call, but not the total.
- The router now has three labels. A message that is misclassified as `other` gets the fixed reply instead of an answer, and the evaluation must check this.
- The general answer can drift off-topic or make claims about the company that aren't true, so it needs its own evaluation cases.
- Off-topic turns now cost one small model call.
- Several different models mean several settings to keep in sync with the evaluations.

## Open questions

- The wording of the out-of-scope reply, and how the user is told to reach a human. No human contact channel is defined yet.
- Exact values for `recursion_limit`, max request length and max tokens per call.
- The Bedrock model ID for Amazon Nova Lite, to confirm before deployment.
- Whether the refund branch's escalation should be confirmed with the user before it is written, when the message also has a product question.

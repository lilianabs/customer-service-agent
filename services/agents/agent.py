"""
Customer service agent graph for AnyCompany Hair Care (first version).

This file holds the whole graph for now: the intent router, the routing edges,
placeholder branch nodes, and the Amazon Bedrock AgentCore entrypoint. It will be
split into the layout in docs/agents_folder_plan.md later.

Graph (see docs/adr/agent_graph.md):

    START -> classify_intent -> next_step -> product_questions | refunds | general | END
    refunds -> escalation (eligible refund request) | next_step
    every other branch node, and escalation -> next_step

The router can return several intents. The branches run one after the other, in
the order the intents appear in the message.

The refunds agent loops between Claude and the read-only orders tools inside its
node, so tool calls and tool results stay out of the shared message history.

Run locally (serves POST /invocations on port 8080, like AgentCore Runtime):
    uv run python services/agents/agent.py
    curl -X POST localhost:8080/invocations -H 'Content-Type: application/json' \\
         -d '{"prompt": "I want a refund for order 1234"}'

Configuration: services/agents/config.json, a copy of the settings this folder
needs, so the folder can be deployed on its own. The AWS_REGION, MCP_RUNTIME_ARN
and MCP_URL environment variables override the file.

Environment: services/agents/.env is loaded at startup if it exists (copy
.env.example to start). Variables already set in the shell win over the file.
LangSmith tracing uses LANGSMITH_TRACING, LANGSMITH_API_KEY, LANGSMITH_PROJECT
and LANGSMITH_ENDPOINT. Tracing stays off unless LANGSMITH_TRACING is true.

Product questions use the v0 approach (retrieve, then generate). Retrieval goes
through rag_client.py, which calls the MCP server's search_product_information
tool. Set mcp.runtime_arn (written by scripts/create_infra.sh) for the deployed
server, or mcp.url / MCP_URL for a local one.
"""

import json
import logging
import operator
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from orders_client import OrdersClient, OrdersClientError
from pydantic import BaseModel, Field
from rag_client import Passage, RagClient, RagClientError
from typing_extensions import TypedDict

logger = logging.getLogger("agents")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# --- Configuration -----------------------------------------------------------

ENV_PATH = Path(__file__).resolve().parent / ".env"
# override=False: variables already set in the shell win over the file.
load_dotenv(ENV_PATH, override=False)

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@dataclass(frozen=True)
class Settings:
    region: str
    router_model_id: str
    router_max_tokens: int
    router_history_messages: int  # recent messages the router sees, for follow-ups
    recursion_limit: int
    product_model_id: str
    product_max_tokens: int
    product_top_k: int  # passages retrieved per product question
    mcp_runtime_arn: str  # MCP server on AgentCore Runtime (SigV4)
    mcp_url: str  # plain MCP URL, e.g. a local server; wins over the ARN
    general_model_id: str  # limited general answer for `other` messages
    general_max_tokens: int
    refunds_model_id: str
    refunds_max_tokens: int
    refunds_max_tool_rounds: int  # model turns that may call tools, per user message


def load_settings(path: Path = CONFIG_PATH) -> Settings:
    """Read the agent settings from config.json.

    AWS_REGION, MCP_RUNTIME_ARN and MCP_URL environment variables override the file.
    """
    data = json.loads(path.read_text())
    agents = data["agents"]
    mcp = data.get("mcp", {})
    return Settings(
        region=os.environ.get("AWS_REGION") or str(data["aws"]["region"]),
        router_model_id=agents["router_model_id"],
        router_max_tokens=agents["router_max_tokens"],
        router_history_messages=agents["router_history_messages"],
        recursion_limit=agents["recursion_limit"],
        product_model_id=agents["product_model_id"],
        product_max_tokens=agents["product_max_tokens"],
        product_top_k=agents["product_top_k"],
        mcp_runtime_arn=os.environ.get("MCP_RUNTIME_ARN") or str(mcp.get("runtime_arn", "")),
        mcp_url=os.environ.get("MCP_URL") or str(mcp.get("url", "")),
        general_model_id=agents["general_model_id"],
        general_max_tokens=agents["general_max_tokens"],
        refunds_model_id=agents["refunds_model_id"],
        refunds_max_tokens=agents["refunds_max_tokens"],
        refunds_max_tool_rounds=agents["refunds_max_tool_rounds"],
    )


SETTINGS = load_settings()

# Fallback for the general node when the model call fails or returns nothing.
# Wording is an open question in the ADR.
OUT_OF_SCOPE_REPLY = (
    "I can help with questions about our hair care products, and with orders and "
    "refunds. For anything else, please contact our customer service team."
)

Intent = Literal["product", "refund", "other"]

INTENT_TO_NODE: dict[str, str] = {
    "product": "product_questions",
    "refund": "refunds",
    "other": "general",
}

ROUTER_SYSTEM_PROMPT = """You classify messages sent to the customer service assistant \
of AnyCompany Hair Care, a hair care products company.

Return one or more of these labels, in the order they appear in the latest user message:
- product: questions about hair care products, ingredients, usage, hair types. \
availability or stock.
- refund: refund or return requests, and questions about an existing order, its \
status, delivery, or the status of a refund.
- other: anything else.

Use earlier messages only to understand follow-ups. Classify the latest user message.
Return "other" only when the message is neither product nor refund."""

PRODUCT_SYSTEM_PROMPT = """You answer product questions for the customer service \
assistant of AnyCompany Hair Care, a hair care products company.

Answer only from the product information passages below. If they do not cover the \
question, say that you don't have that information and suggest contacting customer \
service. Do not guess or add facts that are not in the passages.

Answer only the product part of the customer's latest message. If it also asks about \
an order, a return or a refund, leave that part out: another assistant answers it.

Keep the answer short and friendly, in plain text. Do not list sources; they are \
added after your answer.

Product information passages:
{passages}"""

PRODUCT_FALLBACK_REPLY = (
    "I couldn't find that in our product information right now. Please try "
    "rephrasing your question, or contact our customer service team."
)

GENERAL_SYSTEM_PROMPT = """You are the customer service assistant of AnyCompany Hair \
Care, a hair care products company. The customer's latest message is not a question \
about our products or about an order, a return or a refund.

How to reply:
- Greetings, thanks or small talk: reply briefly and kindly.
- General hair care questions: give a short, general answer. Do not name, recommend \
or describe any specific product.
- Anything else: politely say you can't help with that.
- Always mention that you can help with questions about our hair care products, and \
with orders and refunds.

Rules:
- Never state facts about AnyCompany Hair Care, such as policies, prices, stock, \
opening hours or contact details. You don't have that information.
- Never say you have done or will do anything, such as placing an order or issuing \
a refund.
- If the message also asks about a product, an order, a return or a refund, leave \
that part out: another assistant answers it.

Keep the reply to two or three sentences, in plain text."""

REFUNDS_SYSTEM_PROMPT = """You handle order and refund requests for the customer \
service assistant of AnyCompany Hair Care, a hair care products company.

You can answer questions about an order (its status, delivery, items, refund status) \
and take refund requests. Use the tools to read the order. Never guess or invent \
order details, dates, amounts or policies: use only what the tools return.

- You need an order number (it looks like AC-1001). If the customer hasn't given \
one in this conversation, ask for it and call no tools.
- For an order question, use get_order and, if needed, refund_status.
- For a refund request, call return_policy first.
  - If the order is eligible, call escalate_to_human with a one-sentence summary of \
the request. Then tell the customer the order is eligible under our 30-day return \
policy, the refund amount, and that a member of our team will review the request \
and decide. Do not say the refund is approved.
  - If it is not eligible, explain the reason from return_policy. Do not escalate.
- You cannot approve, deny or issue refunds, and you cannot change orders.
- If a tool returns an error, such as an unknown order, tell the customer plainly \
and ask them to check the order number.

Answer only the order or refund part of the customer's latest message. If it also \
asks a product question or something else, leave that part out: another assistant \
answers it.

Keep the answer short and friendly. Write plain text only: no Markdown (no bold, \
headings or bullet lists) and no emoji, because the chat window shows it as is."""

REFUNDS_FALLBACK_REPLY = (
    "I couldn't check your order right now. Please try again in a moment, or "
    "contact our customer service team."
)

# Order fields the refunds model never sees (PII it doesn't need).
ORDER_PII_FIELDS = ("customer_name", "email")


# --- State -------------------------------------------------------------------


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]  # full history, append mode
    pending_intents: list[str]  # set by the router, consumed by the branches in order
    product_sources: list[str]  # source file names the product answer used this turn
    escalation: dict | None  # refund case summary for a human, this turn only


class RouterDecision(BaseModel):
    """Intents found in the latest user message."""

    intents: list[Intent] = Field(
        description="Intent labels in the order they appear in the message."
    )


# --- Nodes -------------------------------------------------------------------

_router_llm: Runnable | None = None


def _router_model() -> Runnable:
    """Return the router model with structured output, creating it on first use."""
    global _router_llm
    if _router_llm is None:
        llm = ChatBedrockConverse(
            model=SETTINGS.router_model_id,
            region_name=SETTINGS.region,
            temperature=0,
            max_tokens=SETTINGS.router_max_tokens,
        )
        _router_llm = llm.with_structured_output(RouterDecision)
    return _router_llm


def normalize_intents(intents: Sequence[str]) -> list[str]:
    """Dedupe labels keeping order; drop `other` when a real intent is present."""
    seen: list[str] = []
    for intent in intents:
        if intent in INTENT_TO_NODE and intent not in seen:
            seen.append(intent)
    if len(seen) > 1 and "other" in seen:
        seen.remove("other")
    return seen or ["other"]


def classify_intent(state: AgentState) -> dict:
    """Classify the latest user message into product, refund and/or other."""
    history = state["messages"][-SETTINGS.router_history_messages :]
    try:
        result = _router_model().invoke([SystemMessage(ROUTER_SYSTEM_PROMPT), *history])
        raw = RouterDecision.model_validate(result).intents
    except Exception:
        logger.exception("intent router failed, falling back to 'other'")
        raw = []
    intents = normalize_intents(raw)
    logger.info("intents=%s", intents)
    return {"pending_intents": intents}


_product_llm: Runnable | None = None
_rag: RagClient | None = None


def _product_model() -> Runnable:
    """Return the product questions model, creating it on first use."""
    global _product_llm
    if _product_llm is None:
        _product_llm = ChatBedrockConverse(
            model=SETTINGS.product_model_id,
            region_name=SETTINGS.region,
            temperature=0,
            max_tokens=SETTINGS.product_max_tokens,
        )
    return _product_llm


def _rag_client() -> RagClient:
    """Return the knowledge base client, creating it on first use."""
    global _rag
    if _rag is None:
        _rag = RagClient(
            region=SETTINGS.region,
            runtime_arn=SETTINGS.mcp_runtime_arn,
            url=SETTINGS.mcp_url,
        )
    return _rag


def source_name(source: str) -> str:
    """File name of a knowledge base source URI (s3://bucket/knowledge_base/x.md -> x.md)."""
    return source.rstrip("/").rsplit("/", 1)[-1]


def format_passages(passages: Sequence[Passage]) -> str:
    """Numbered passage block for the prompt, each with its source file name."""
    return "\n\n".join(
        f"[{i}] (source: {source_name(p['source'])})\n{p['passage']}"
        for i, p in enumerate(passages, start=1)
    )


def unique_sources(passages: Sequence[Passage]) -> list[str]:
    """Source file names in retrieval order, without duplicates."""
    names: list[str] = []
    for p in passages:
        name = source_name(p["source"])
        if name and name not in names:
            names.append(name)
    return names


def latest_user_message(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def product_questions(state: AgentState) -> dict:
    """Product questions, v0 RAG workflow: retrieve passages, then answer from them."""
    remaining = state["pending_intents"][1:]
    query = latest_user_message(state["messages"])

    try:
        passages = _rag_client().search(query, SETTINGS.product_top_k)
    except RagClientError:
        logger.exception("knowledge base search failed")
        passages = []

    if not passages:
        return {
            "messages": [AIMessage(PRODUCT_FALLBACK_REPLY)],
            "product_sources": [],
            "pending_intents": remaining,
        }

    system = SystemMessage(PRODUCT_SYSTEM_PROMPT.format(passages=format_passages(passages)))
    history = state["messages"][-SETTINGS.router_history_messages :]
    answer = _product_model().invoke([system, *history])

    sources = unique_sources(passages)
    reply = f"{str(answer.content).strip()}\n\nSources: {', '.join(sources)}"
    return {
        "messages": [AIMessage(reply)],
        "product_sources": sources,
        "pending_intents": remaining,
    }


_refunds_llm: ChatBedrockConverse | None = None
_orders: OrdersClient | None = None


def _refunds_model() -> ChatBedrockConverse:
    """Return the refunds model (tools not bound yet), creating it on first use."""
    global _refunds_llm
    if _refunds_llm is None:
        _refunds_llm = ChatBedrockConverse(
            model=SETTINGS.refunds_model_id,
            region_name=SETTINGS.region,
            temperature=0,
            max_tokens=SETTINGS.refunds_max_tokens,
        )
    return _refunds_llm


def _orders_client() -> OrdersClient:
    """Return the orders client, creating it on first use."""
    global _orders
    if _orders is None:
        _orders = OrdersClient(
            region=SETTINGS.region,
            runtime_arn=SETTINGS.mcp_runtime_arn,
            url=SETTINGS.mcp_url,
        )
    return _orders


def without_pii(order: dict) -> dict:
    """The order without the customer's name and email."""
    return {k: v for k, v in order.items() if k not in ORDER_PII_FIELDS}


def build_case_summary(
    orders: OrdersClient, order_number: str, request_summary: str
) -> tuple[dict | None, str]:
    """Check eligibility in code and build the case for a human.

    Returns (case, reason): case is None when the order is not eligible.
    The case holds no customer name or email.
    """
    policy = orders.return_policy(order_number)
    if not policy.get("eligible"):
        return None, str(policy.get("reason", "Not eligible."))
    order = orders.get_order(order_number)
    amount = orders.refund_amount(order_number)
    case = {
        "order_number": order_number,
        "items": order.get("items", []),
        "purchased": order.get("purchased"),
        "days_since_purchase": policy.get("days_since_purchase"),
        "refund_amount": amount.get("refund_amount"),
        "policy_reason": policy.get("reason"),
        "request_summary": request_summary,
    }
    return case, str(policy.get("reason", ""))


def make_refund_tools(orders: OrdersClient, cases: list[dict]) -> list[BaseTool]:
    """The tools bound to the refunds model. Escalated cases are appended to `cases`.

    Read-only order tools plus escalate_to_human. There is no tool that issues a
    refund. Errors are returned to the model as text, so it can tell the customer.
    """

    def guarded(call):
        try:
            return json.dumps(call())
        except OrdersClientError as exc:
            return f"Error: {exc}"

    @tool
    def get_order(order_number: str) -> str:
        """Get an order's details: items, status, purchase date and refund status.

        Args:
            order_number: The order number the customer gave, for example AC-1001.
        """
        return guarded(lambda: without_pii(orders.get_order(order_number)))

    @tool
    def return_policy(order_number: str) -> str:
        """Check whether an order is eligible for a refund under the 30-day return policy.

        Args:
            order_number: The order number the customer gave, for example AC-1001.
        """
        return guarded(lambda: orders.return_policy(order_number))

    @tool
    def refund_status(order_number: str) -> str:
        """Get an order's refund status (null when no refund has been made).

        Args:
            order_number: The order number the customer gave, for example AC-1001.
        """
        return guarded(lambda: orders.refund_status(order_number))

    @tool
    def refund_amount(order_number: str) -> str:
        """Get the amount a refund of the order would be. Does not issue a refund.

        Args:
            order_number: The order number the customer gave, for example AC-1001.
        """
        return guarded(lambda: orders.refund_amount(order_number))

    @tool
    def escalate_to_human(order_number: str, request_summary: str) -> str:
        """Send an eligible refund request to a human, who decides the refund.

        Use only after return_policy says the order is eligible. Escalate once per order.

        Args:
            order_number: The order number, for example AC-1001.
            request_summary: One sentence describing what the customer asked for and why.
        """
        if any(c["order_number"] == order_number for c in cases):
            return "Already escalated: a member of the team will review the refund."
        try:
            case, reason = build_case_summary(orders, order_number, request_summary)
        except OrdersClientError as exc:
            return f"Error: {exc}"
        if case is None:
            return f"Not escalated: {reason}"
        cases.append(case)
        return "Escalated: a member of the team will review the refund and decide."

    return [get_order, return_policy, refund_status, refund_amount, escalate_to_human]


def run_tool_call(tools_by_name: dict[str, BaseTool], call: dict) -> ToolMessage:
    """Run one tool call from the model and wrap the result for the model."""
    selected = tools_by_name.get(call["name"])
    if selected is None:
        content = f"Error: unknown tool {call['name']}"
    else:
        content = str(selected.invoke(call["args"]))
    return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"])


def refunds(state: AgentState) -> dict:
    """Refunds agent: Claude with the orders tools, looping until it answers.

    The loop runs on a local message list, so only the final answer joins the
    conversation history. At most `refunds_max_tool_rounds` model turns run tools.
    """
    remaining = state["pending_intents"][1:]
    cases: list[dict] = []
    tools = make_refund_tools(_orders_client(), cases)
    tools_by_name = {t.name: t for t in tools}
    history = state["messages"][-SETTINGS.router_history_messages :]
    messages: list[BaseMessage] = [SystemMessage(REFUNDS_SYSTEM_PROMPT), *history]

    reply = ""
    try:
        model = _refunds_model().bind_tools(tools)
        for round_number in range(SETTINGS.refunds_max_tool_rounds + 1):
            answer = model.invoke(messages)
            calls = getattr(answer, "tool_calls", None) or []
            if not calls:
                reply = answer.text.strip()
                break
            if round_number == SETTINGS.refunds_max_tool_rounds:
                logger.warning("refunds agent hit the tool round limit")
                break
            messages.append(answer)
            messages.extend(run_tool_call(tools_by_name, call) for call in calls)
    except Exception:
        logger.exception("refunds agent failed, using the fallback reply")

    return {
        "messages": [AIMessage(reply or REFUNDS_FALLBACK_REPLY)],
        "pending_intents": remaining,
        "escalation": cases[0] if cases else None,
    }


def escalation(state: AgentState) -> dict:
    """Hand the refund case to a human. For now: one structured log line (CloudWatch).

    A real channel (ticket, queue, email) plugs in here.
    """
    logger.info(json.dumps({"event": "refund_escalation", **(state.get("escalation") or {})}))
    return {}


_general_llm: Runnable | None = None


def _general_model() -> Runnable:
    """Return the general answer model, creating it on first use."""
    global _general_llm
    if _general_llm is None:
        _general_llm = ChatBedrockConverse(
            model=SETTINGS.general_model_id,
            region_name=SETTINGS.region,
            temperature=0,
            max_tokens=SETTINGS.general_max_tokens,
        )
    return _general_llm


def general(state: AgentState) -> dict:
    """Limited general answer for `other` messages; fixed reply if the model fails."""
    history = state["messages"][-SETTINGS.router_history_messages :]
    try:
        answer = _general_model().invoke([SystemMessage(GENERAL_SYSTEM_PROMPT), *history])
        reply = str(answer.content).strip()
    except Exception:
        logger.exception("general answer failed, using the fixed out-of-scope reply")
        reply = ""
    return {
        "messages": [AIMessage(reply or OUT_OF_SCOPE_REPLY)],
        "pending_intents": state["pending_intents"][1:],
    }


# --- Routing -----------------------------------------------------------------


def next_step(state: AgentState) -> str:
    """Send the run to the node for the next pending intent, or end it."""
    pending = state.get("pending_intents") or []
    if not pending:
        return END
    return INTENT_TO_NODE[pending[0]]


def after_refunds(state: AgentState) -> str:
    """Escalate an eligible refund request, otherwise go on to the next intent."""
    if state.get("escalation"):
        return "escalation"
    return next_step(state)


# --- Graph -------------------------------------------------------------------

BRANCHES = ["product_questions", "refunds", "general", END]


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("product_questions", product_questions)
    builder.add_node("refunds", refunds)
    builder.add_node("escalation", escalation)
    builder.add_node("general", general)

    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges("classify_intent", next_step, BRANCHES)
    builder.add_conditional_edges("refunds", after_refunds, ["escalation", *BRANCHES])
    for node in ("product_questions", "escalation", "general"):
        builder.add_conditional_edges(node, next_step, BRANCHES)

    return builder.compile(checkpointer=checkpointer)


graph = build_graph(checkpointer=InMemorySaver())


# --- AgentCore entrypoint ----------------------------------------------------

app = BedrockAgentCoreApp()


def run_turn(prompt: str, thread_id: str) -> dict:
    """Run one user message through the graph and return this turn's reply."""
    run_config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": SETTINGS.recursion_limit,
    }
    previous = graph.get_state(run_config).values.get("messages", [])
    inputs: AgentState = {
        "messages": [HumanMessage(prompt)],
        "pending_intents": [],
        "product_sources": [],  # reset, so sources from an earlier turn don't leak
        "escalation": None,  # same for an earlier turn's refund case
    }
    result = graph.invoke(inputs, config=run_config)
    new_messages = result["messages"][len(previous) + 1 :]
    replies = [m.content for m in new_messages if isinstance(m, AIMessage)]
    return {
        "reply": "\n\n".join(str(r) for r in replies),
        "sources": result.get("product_sources", []),
        "escalation": result.get("escalation"),
        "session_id": thread_id,
    }


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    prompt = payload.get("prompt", "")
    thread_id = (
        getattr(context, "session_id", None) or payload.get("session_id") or "local"
    )
    return run_turn(prompt, thread_id)


if __name__ == "__main__":
    app.run()

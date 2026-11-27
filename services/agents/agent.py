"""
Customer service agent graph for AnyCompany Hair Care (first version).

This file holds the whole graph for now: the intent router, the routing edges,
placeholder branch nodes, and the Amazon Bedrock AgentCore entrypoint. It will be
split into the layout in docs/agents_folder_plan.md later.

Graph (see docs/adr/agent_graph.md):

    START -> classify_intent -> next_step -> product_questions | refunds | out_of_scope | END
    each branch node -> next_step

The router can return several intents. The branches run one after the other, in
the order the intents appear in the message.

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
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
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
    )


SETTINGS = load_settings()

# Wording is an open question in the ADR.
OUT_OF_SCOPE_REPLY = (
    "I can help with questions about our hair care products, and with orders and "
    "refunds. For anything else, please contact our customer service team."
)

Intent = Literal["product", "refund", "other"]

INTENT_TO_NODE: dict[str, str] = {
    "product": "product_questions",
    "refund": "refunds",
    "other": "out_of_scope",
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


# --- State -------------------------------------------------------------------


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]  # full history, append mode
    pending_intents: list[str]  # set by the router, consumed by the branches in order
    product_sources: list[str]  # source file names the product answer used this turn


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


def refunds(state: AgentState) -> dict:
    """Placeholder until the refunds agent is built."""
    reply = AIMessage("[refunds agent not built yet]")
    return {"messages": [reply], "pending_intents": state["pending_intents"][1:]}


def out_of_scope(state: AgentState) -> dict:
    """Fixed out-of-scope reply. No model call."""
    return {
        "messages": [AIMessage(OUT_OF_SCOPE_REPLY)],
        "pending_intents": state["pending_intents"][1:],
    }


# --- Routing -----------------------------------------------------------------


def next_step(state: AgentState) -> str:
    """Send the run to the node for the next pending intent, or end it."""
    pending = state.get("pending_intents") or []
    if not pending:
        return END
    return INTENT_TO_NODE[pending[0]]


# --- Graph -------------------------------------------------------------------

BRANCHES = ["product_questions", "refunds", "out_of_scope", END]


def build_graph(checkpointer=None):
    builder = StateGraph(AgentState)
    builder.add_node("classify_intent", classify_intent)
    builder.add_node("product_questions", product_questions)
    builder.add_node("refunds", refunds)
    builder.add_node("out_of_scope", out_of_scope)

    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges("classify_intent", next_step, BRANCHES)
    for node in ("product_questions", "refunds", "out_of_scope"):
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
    }
    result = graph.invoke(inputs, config=run_config)
    new_messages = result["messages"][len(previous) + 1 :]
    replies = [m.content for m in new_messages if isinstance(m, AIMessage)]
    return {
        "reply": "\n\n".join(str(r) for r in replies),
        "sources": result.get("product_sources", []),
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

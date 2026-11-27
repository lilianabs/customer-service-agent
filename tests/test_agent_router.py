"""
Tests for the intent router graph in services/agents/agent.py.

Three groups:
  - routing logic: no model call, always runs.
  - live routing: calls amazon.nova-micro-v1:0 on Bedrock. Marked `live`.
  - memory: a follow-up on the same thread_id keeps the earlier turn. Calls Bedrock.

Run from the project root:
    uv run pytest                    # everything
    uv run pytest -m "not live"      # routing logic only, no AWS calls

Needs AWS credentials with Bedrock access in the region from services/agents/config.json.

The product questions node's knowledge base client and model, and the general
node's model, are fakes here, so these tests check routing only and don't need
the MCP server.
"""

import uuid

import agent
import pytest
from conftest import FAKE_GENERAL_REPLY, FAKE_PRODUCT_REPLY
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END

PRODUCT_REPLY = FAKE_PRODUCT_REPLY
REFUND_REPLY = "[refunds agent not built yet]"
OTHER_REPLY = FAKE_GENERAL_REPLY


@pytest.fixture(autouse=True)
def _stub_branch_nodes(fake_product, fake_general):
    """Every test in this file uses the fake product and general node dependencies."""
    return fake_product, fake_general


def new_thread_id() -> str:
    return f"test-{uuid.uuid4()}"


# --- Routing logic (no model call) -------------------------------------------


@pytest.mark.parametrize(
    ("pending", "expected"),
    [
        (["product", "refund"], "product_questions"),
        (["refund"], "refunds"),
        (["other"], "general"),
        ([], END),
    ],
)
def test_next_step_picks_the_first_pending_intent(pending, expected):
    state: agent.AgentState = {"messages": [], "pending_intents": pending, "product_sources": []}
    assert agent.next_step(state) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["refund", "product", "refund"], ["refund", "product"]),
        (["refund", "other"], ["refund"]),
        ([], ["other"]),
    ],
)
def test_normalize_intents(raw, expected):
    assert agent.normalize_intents(raw) == expected


# --- Live routing (calls Bedrock) --------------------------------------------

LIVE_CASES = [
    ("Does the argan shampoo work on curly hair?", [PRODUCT_REPLY]),
    ("I want to return order 1234", [REFUND_REPLY]),
    ("Where is my order?", [REFUND_REPLY]),
    ("What's the weather today?", [OTHER_REPLY]),
    (
        "Is the conditioner sulfate-free? Also I want a refund for order 1234",
        [PRODUCT_REPLY, REFUND_REPLY],
    ),
    (
        "I want a refund for order 1234. Also, is the conditioner sulfate-free?",
        [REFUND_REPLY, PRODUCT_REPLY],
    ),
]


@pytest.mark.live
@pytest.mark.parametrize(("message", "expected"), LIVE_CASES)
def test_live_routing(message, expected):
    reply = agent.run_turn(message, new_thread_id())["reply"]
    assert reply == "\n\n".join(expected)


# --- Memory (calls Bedrock) --------------------------------------------------


@pytest.mark.live
def test_follow_up_keeps_earlier_turn_on_same_thread():
    thread_id = new_thread_id()
    agent.run_turn("Does the argan shampoo work on curly hair?", thread_id)
    agent.run_turn("And how often should I use it?", thread_id)

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    messages = agent.graph.get_state(config).values["messages"]
    # Two user messages and their two replies.
    assert len(messages) == 4

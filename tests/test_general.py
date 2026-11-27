"""
Tests for the general node, which gives a limited general answer to `other` messages.

The chat model is a fake (see conftest.py), so these tests make no AWS calls,
except the ones marked `live`.
"""

import uuid

import agent
import pytest
from conftest import FAKE_GENERAL_REPLY
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage


def node_state(*messages: AnyMessage, pending: tuple[str, ...] = ("other",)) -> agent.AgentState:
    return {"messages": list(messages), "pending_intents": list(pending), "product_sources": []}


# --- Node --------------------------------------------------------------------


def test_replies_with_the_model_answer_and_consumes_the_intent(fake_general):
    out = agent.general(node_state(HumanMessage("Hi there!")))

    assert out["messages"][0].content == FAKE_GENERAL_REPLY
    assert out["pending_intents"] == []
    assert "product_sources" not in out


def test_keeps_later_pending_intents(fake_general):
    out = agent.general(node_state(HumanMessage("Hi"), pending=("other", "refund")))

    assert out["pending_intents"] == ["refund"]


def test_prompt_is_system_prompt_plus_recent_history(fake_general):
    limit = agent.SETTINGS.router_history_messages
    history: list[AnyMessage] = []
    for i in range(limit):
        history += [HumanMessage(f"question {i}"), AIMessage(f"answer {i}")]
    history.append(HumanMessage("Thanks!"))

    agent.general(node_state(*history))

    [sent] = fake_general.calls
    assert sent[0] == SystemMessage(agent.GENERAL_SYSTEM_PROMPT)
    assert sent[1:] == history[-limit:]
    assert sent[-1].content == "Thanks!"


def test_model_error_gives_fixed_reply(fake_general):
    fake_general.error = RuntimeError("Bedrock throttled")
    out = agent.general(node_state(HumanMessage("What's the weather?")))

    assert out["messages"][0].content == agent.OUT_OF_SCOPE_REPLY
    assert out["pending_intents"] == []


def test_empty_answer_gives_fixed_reply(fake_general):
    fake_general.reply = "   "
    out = agent.general(node_state(HumanMessage("What's the weather?")))

    assert out["messages"][0].content == agent.OUT_OF_SCOPE_REPLY


# --- Graph -------------------------------------------------------------------


def test_other_intent_runs_the_general_node(fake_general, fake_router):
    fake_router(["other"])
    result = agent.run_turn("What's the weather today?", f"test-{uuid.uuid4()}")

    assert result["reply"] == FAKE_GENERAL_REPLY
    assert result["sources"] == []


# --- Live (Bedrock) ----------------------------------------------------------


@pytest.mark.live
@pytest.mark.parametrize("message", ["Hi there!", "What's the weather today?"])
def test_live_general_answer(message):
    reply = agent.general(node_state(HumanMessage(message)))["messages"][0].content

    assert reply
    assert reply != agent.OUT_OF_SCOPE_REPLY
    assert "Sources:" not in reply

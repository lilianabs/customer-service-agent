"""
Tests for the product questions node (v0 RAG workflow) and rag_client.

The knowledge base client and the chat models are fakes (see conftest.py), so
these tests make no AWS calls, except the one marked `live`.
"""

import uuid
from urllib.parse import unquote

import agent
import pytest
from conftest import FAKE_PRODUCT_REPLY, FAKE_REFUND_REPLY
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from rag_client import RagClient, RagClientError, agentcore_mcp_url


def node_state(*messages: AnyMessage, pending: tuple[str, ...] = ("product",)) -> agent.AgentState:
    return {"messages": list(messages), "pending_intents": list(pending), "product_sources": []}


# --- Node --------------------------------------------------------------------


def test_answers_from_passages_and_lists_unique_sources(fake_product):
    out = agent.product_questions(node_state(HumanMessage("Is argan shampoo good for curls?")))

    assert out["messages"][0].content == FAKE_PRODUCT_REPLY
    assert out["product_sources"] == ["argan_shampoo.md", "hair_type_guide.md"]
    assert out["pending_intents"] == []


def test_searches_with_latest_user_message_and_configured_top_k(fake_product):
    state = node_state(
        HumanMessage("Hi"),
        AIMessage("Hello!"),
        HumanMessage("How often should I use the argan shampoo?"),
    )
    agent.product_questions(state)

    assert fake_product.rag.calls == [
        ("How often should I use the argan shampoo?", agent.SETTINGS.product_top_k)
    ]


def test_passages_and_sources_are_in_the_prompt(fake_product):
    prompt = agent.PRODUCT_SYSTEM_PROMPT.format(
        passages=agent.format_passages(fake_product.rag.passages)
    )
    assert "[1] (source: argan_shampoo.md)" in prompt
    assert "Curly hair needs moisture." in prompt


def test_no_passages_gives_fallback_without_model_call(fake_product, monkeypatch):
    fake_product.rag.passages = []

    def fail():
        raise AssertionError("model must not be called")

    monkeypatch.setattr(agent, "_product_model", fail)
    out = agent.product_questions(node_state(HumanMessage("Do you sell hats?")))

    assert out["messages"][0].content == agent.PRODUCT_FALLBACK_REPLY
    assert out["product_sources"] == []


def test_search_error_gives_fallback(fake_product):
    fake_product.rag.error = RagClientError("MCP server unreachable")
    out = agent.product_questions(node_state(HumanMessage("Is it sulfate-free?")))

    assert out["messages"][0].content == agent.PRODUCT_FALLBACK_REPLY
    assert out["pending_intents"] == []


def test_product_then_refund_runs_both_branches(fake_product, fake_refunds, fake_router):
    fake_router(["product", "refund"])
    result = agent.run_turn("Is it sulfate-free? Also refund order 1234", f"test-{uuid.uuid4()}")

    assert result["reply"] == f"{FAKE_PRODUCT_REPLY}\n\n{FAKE_REFUND_REPLY}"
    assert result["sources"] == ["argan_shampoo.md", "hair_type_guide.md"]


def test_sources_reset_on_a_turn_without_product_intent(fake_product, fake_general, fake_router):
    thread_id = f"test-{uuid.uuid4()}"
    fake_router(["product"])
    agent.run_turn("Is argan shampoo good for curls?", thread_id)
    fake_router(["other"])
    result = agent.run_turn("What's the weather?", thread_id)

    assert result["sources"] == []


# --- rag_client --------------------------------------------------------------


def test_url_from_runtime_arn_is_encoded_agentcore_url():
    arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/mcp_server_hair_care-abc"
    client = RagClient(region="us-east-1", runtime_arn=arn)

    assert client.signed
    assert client.url == agentcore_mcp_url(arn, "us-east-1")
    assert client.url.startswith("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/")
    assert client.url.endswith("/invocations?qualifier=DEFAULT")
    assert unquote(client.url.split("/runtimes/")[1].split("/invocations")[0]) == arn


def test_plain_url_wins_and_is_unsigned():
    client = RagClient(region="us-east-1", runtime_arn="arn:x", url="http://localhost:8000/mcp")

    assert client.url == "http://localhost:8000/mcp"
    assert not client.signed


def test_no_endpoint_raises_rag_client_error():
    with pytest.raises(RagClientError):
        RagClient(region="us-east-1").search("anything", 5)


# --- Live (MCP server and Bedrock) -------------------------------------------


@pytest.mark.live
def test_live_product_answer_has_sources():
    if not (agent.SETTINGS.mcp_runtime_arn or agent.SETTINGS.mcp_url):
        pytest.skip("No MCP endpoint configured; run ./scripts/create_infra.sh first")

    result = agent.run_turn("How often should I wash my hair?", f"test-{uuid.uuid4()}")

    assert result["sources"], result
    assert "Sources:" in result["reply"]
    assert result["reply"] != agent.PRODUCT_FALLBACK_REPLY

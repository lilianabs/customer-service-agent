"""
Tests for the refunds agent (Claude with the orders tools), the escalation node,
orders_client and the shared mcp_client parsing.

The orders client and the model are fakes (see conftest.py), so these tests make
no AWS calls, except the ones marked `live`.
"""

import json
import logging
import uuid
from types import SimpleNamespace

import agent
import pytest
from conftest import FAKE_PRODUCT_REPLY, FAKE_REFUND_REPLY, tool_call
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from mcp_client import McpClientError, McpToolError, parse_tool_result
from orders_client import OrdersClient, OrdersClientError

REFUND_TOOLS = {"get_order", "return_policy", "refund_status", "refund_amount", "escalate_to_human"}


def node_state(*messages: AnyMessage, pending: tuple[str, ...] = ("refund",)) -> agent.AgentState:
    return {
        "messages": list(messages),
        "pending_intents": list(pending),
        "product_sources": [],
        "escalation": None,
    }


def tool_results(fake_refunds) -> list[ToolMessage]:
    """The tool messages the model saw on its last call."""
    return [m for m in fake_refunds.model.calls[-1] if isinstance(m, ToolMessage)]


# --- Tools -------------------------------------------------------------------


def test_tools_are_read_only_plus_escalation(fake_refunds):
    agent.refunds(node_state(HumanMessage("Where is my order AC-1001?")))

    assert {t.name for t in fake_refunds.model.bound_tools} == REFUND_TOOLS


def test_orders_client_cannot_issue_refunds():
    assert not hasattr(OrdersClient, "apply_refund")


def test_get_order_tool_hides_name_and_email(fake_refunds):
    fake_refunds.model.script = [tool_call("get_order", order_number="AC-1001")]
    agent.refunds(node_state(HumanMessage("Where is my order AC-1001?")))

    [result] = tool_results(fake_refunds)
    order = json.loads(str(result.content))
    assert order["status"] == "delivered"
    assert "customer_name" not in order
    assert "email" not in order


# --- Node --------------------------------------------------------------------


def test_tool_loop_returns_only_the_final_answer(fake_refunds):
    fake_refunds.model.script = [
        tool_call("get_order", order_number="AC-1001"),
        tool_call("refund_status", "call-2", order_number="AC-1001"),
    ]
    out = agent.refunds(node_state(HumanMessage("Where is my order AC-1001?")))

    assert [m.content for m in out["messages"]] == [FAKE_REFUND_REPLY]
    assert out["pending_intents"] == []
    assert out["escalation"] is None
    assert fake_refunds.orders.calls == [("get_order", "AC-1001"), ("refund_status", "AC-1001")]
    assert len(fake_refunds.model.calls) == 3


def test_prompt_is_system_prompt_plus_recent_history(fake_refunds):
    limit = agent.SETTINGS.router_history_messages
    history: list[AnyMessage] = []
    for i in range(limit):
        history += [HumanMessage(f"question {i}"), AIMessage(f"answer {i}")]
    history.append(HumanMessage("AC-1001"))

    agent.refunds(node_state(*history))

    [sent] = fake_refunds.model.calls
    assert sent[0] == SystemMessage(agent.REFUNDS_SYSTEM_PROMPT)
    assert sent[1:] == history[-limit:]


def test_eligible_refund_is_escalated_with_a_case_summary(fake_refunds):
    fake_refunds.model.script = [
        tool_call("return_policy", order_number="AC-1001"),
        tool_call("escalate_to_human", "call-2", order_number="AC-1001", request_summary="Wants a refund."),
    ]
    out = agent.refunds(node_state(HumanMessage("I want a refund for AC-1001")))

    case = out["escalation"]
    assert case["order_number"] == "AC-1001"
    assert case["refund_amount"] == 30
    assert case["items"] == [{"product": "Weekly Repair Mask", "qty": 1, "price": 30}]
    assert case["request_summary"] == "Wants a refund."
    assert "email" not in json.dumps(case)
    assert tool_results(fake_refunds)[-1].content.startswith("Escalated")


@pytest.mark.parametrize(
    ("order_number", "reason"),
    [("AC-1002", "30-day return window has passed"), ("AC-1003", "already been refunded")],
)
def test_ineligible_refund_is_not_escalated(fake_refunds, order_number, reason):
    fake_refunds.model.script = [
        tool_call("escalate_to_human", order_number=order_number, request_summary="Refund."),
    ]
    out = agent.refunds(node_state(HumanMessage(f"Refund {order_number}")))

    assert out["escalation"] is None
    [result] = tool_results(fake_refunds)
    assert result.content.startswith("Not escalated")
    assert reason in result.content


def test_escalating_twice_keeps_one_case(fake_refunds):
    escalate = {"order_number": "AC-1001", "request_summary": "Refund."}
    fake_refunds.model.script = [
        tool_call("escalate_to_human", **escalate),
        tool_call("escalate_to_human", "call-2", **escalate),
    ]
    out = agent.refunds(node_state(HumanMessage("Refund AC-1001")))

    assert out["escalation"]["order_number"] == "AC-1001"
    assert tool_results(fake_refunds)[-1].content.startswith("Already escalated")


def test_unknown_order_error_goes_back_to_the_model(fake_refunds):
    fake_refunds.model.script = [tool_call("get_order", order_number="AC-9999")]
    out = agent.refunds(node_state(HumanMessage("Where is AC-9999?")))

    assert out["messages"][0].content == FAKE_REFUND_REPLY
    [result] = tool_results(fake_refunds)
    assert result.content == "Error: Order AC-9999 not found"


def test_orders_service_failure_goes_back_to_the_model(fake_refunds):
    fake_refunds.orders.error = OrdersClientError("MCP server unreachable")
    fake_refunds.model.script = [tool_call("return_policy", order_number="AC-1001")]
    out = agent.refunds(node_state(HumanMessage("Refund AC-1001")))

    assert out["messages"][0].content == FAKE_REFUND_REPLY
    assert tool_results(fake_refunds)[0].content == "Error: MCP server unreachable"
    assert out["escalation"] is None


def test_model_error_gives_fallback(fake_refunds):
    fake_refunds.model.error = RuntimeError("Bedrock throttled")
    out = agent.refunds(node_state(HumanMessage("Refund AC-1001")))

    assert out["messages"][0].content == agent.REFUNDS_FALLBACK_REPLY
    assert out["pending_intents"] == []


def test_tool_round_limit_gives_fallback(fake_refunds):
    rounds = agent.SETTINGS.refunds_max_tool_rounds
    fake_refunds.model.script = [
        tool_call("get_order", f"call-{i}", order_number="AC-1001") for i in range(rounds + 1)
    ]
    out = agent.refunds(node_state(HumanMessage("Where is AC-1001?")))

    assert out["messages"][0].content == agent.REFUNDS_FALLBACK_REPLY
    assert len(fake_refunds.orders.calls) == rounds  # the last turn's tools don't run
    assert len(fake_refunds.model.calls) == rounds + 1


def test_unknown_tool_name_is_reported_to_the_model(fake_refunds):
    fake_refunds.model.script = [tool_call("apply_refund", order_number="AC-1001")]
    agent.refunds(node_state(HumanMessage("Refund AC-1001 now")))

    assert tool_results(fake_refunds)[0].content == "Error: unknown tool apply_refund"
    assert fake_refunds.orders.calls == []


# --- Graph -------------------------------------------------------------------


def escalation_script() -> list[AIMessage]:
    return [
        tool_call("escalate_to_human", order_number="AC-1001", request_summary="Wants a refund."),
    ]


def test_eligible_refund_runs_escalation_and_logs_the_case(fake_refunds, fake_router, caplog):
    fake_router(["refund"])
    fake_refunds.model.script = escalation_script()
    with caplog.at_level(logging.INFO, logger="agents"):
        result = agent.run_turn("I want a refund for AC-1001", f"test-{uuid.uuid4()}")

    assert result["reply"] == FAKE_REFUND_REPLY
    assert result["escalation"]["order_number"] == "AC-1001"
    logged = [json.loads(r.getMessage()) for r in caplog.records if "refund_escalation" in r.getMessage()]
    assert logged == [{"event": "refund_escalation", **result["escalation"]}]


def test_escalation_resets_on_the_next_turn(fake_refunds, fake_router):
    thread_id = f"test-{uuid.uuid4()}"
    fake_router(["refund"])
    fake_refunds.model.script = escalation_script()
    agent.run_turn("I want a refund for AC-1001", thread_id)
    result = agent.run_turn("Thanks, and where is it now?", thread_id)

    assert result["escalation"] is None


def test_refund_then_product_still_runs_product_after_escalation(fake_refunds, fake_product, fake_router):
    fake_router(["refund", "product"])
    fake_refunds.model.script = escalation_script()
    result = agent.run_turn("Refund AC-1001. Also, is the mask sulfate-free?", f"test-{uuid.uuid4()}")

    assert result["reply"] == f"{FAKE_REFUND_REPLY}\n\n{FAKE_PRODUCT_REPLY}"
    assert result["escalation"] is not None


def test_tool_messages_stay_out_of_the_history(fake_refunds, fake_router):
    fake_router(["refund"])
    fake_refunds.model.script = [tool_call("get_order", order_number="AC-1001")]
    thread_id = f"test-{uuid.uuid4()}"
    agent.run_turn("Where is AC-1001?", thread_id)

    messages = agent.graph.get_state({"configurable": {"thread_id": thread_id}}).values["messages"]
    assert [type(m) for m in messages] == [HumanMessage, AIMessage]


# --- mcp_client parsing -------------------------------------------------------


def tool_result(*, text: str | None = None, structured=None, is_error: bool = False):
    content = [SimpleNamespace(type="text", text=text)] if text is not None else []
    return SimpleNamespace(isError=is_error, structuredContent=structured, content=content)


def test_parse_prefers_structured_content():
    assert parse_tool_result("t", tool_result(structured={"a": 1}, text="ignored")) == {"a": 1}


def test_parse_unwraps_the_result_wrapper():
    assert parse_tool_result("t", tool_result(structured={"result": 30})) == 30


def test_parse_decodes_json_text():
    result = tool_result(text='{"refund_amount": 30}')
    assert parse_tool_result("t", result) == {"refund_amount": 30}


def test_parse_raises_tool_error():
    result = tool_result(text="Error executing tool get_order: Not found: /orders/X", is_error=True)
    with pytest.raises(McpToolError, match="Not found"):
        parse_tool_result("get_order", result)


def test_parse_rejects_non_json_text():
    with pytest.raises(McpClientError):
        parse_tool_result("t", tool_result(text="not json"))


def test_orders_client_maps_not_found(monkeypatch):
    client = OrdersClient(region="us-east-1", url="http://localhost:8000/mcp")

    def not_found(name, arguments):
        raise McpToolError("Error executing tool get_order: Not found: /orders/AC-9999")

    monkeypatch.setattr(client._mcp, "call_tool", not_found)
    with pytest.raises(OrdersClientError, match="Order AC-9999 not found"):
        client.get_order("AC-9999")


def test_orders_client_without_endpoint_raises():
    with pytest.raises(OrdersClientError):
        OrdersClient(region="us-east-1").get_order("AC-1001")


# --- Live (MCP server and Bedrock) -------------------------------------------


def live_turn(message: str, thread_id: str | None = None) -> dict:
    if not (agent.SETTINGS.mcp_runtime_arn or agent.SETTINGS.mcp_url):
        pytest.skip("No MCP endpoint configured; run ./scripts/create_infra.sh first")
    return agent.run_turn(message, thread_id or f"test-{uuid.uuid4()}")


@pytest.mark.live
def test_live_eligible_refund_is_escalated():
    result = live_turn("I want a refund for order AC-1001")

    assert result["escalation"] is not None, result
    assert result["escalation"]["order_number"] == "AC-1001"
    assert result["escalation"]["refund_amount"] == 30


@pytest.mark.live
def test_live_refund_outside_the_window_is_not_escalated():
    result = live_turn("Please refund my order AC-1002")

    assert result["escalation"] is None, result
    assert "30" in result["reply"]


@pytest.mark.live
def test_live_order_status_is_not_escalated():
    result = live_turn("Where is my order AC-1001?")

    assert result["escalation"] is None, result
    assert "deliver" in result["reply"].lower()


@pytest.mark.live
def test_live_asks_for_the_order_number_then_escalates():
    thread_id = f"test-{uuid.uuid4()}"
    first = live_turn("I want a refund for my hair mask", thread_id)
    assert first["escalation"] is None
    assert "order number" in first["reply"].lower()

    second = live_turn("It's AC-1001", thread_id)
    assert second["escalation"] is not None, second

"""Shared fakes for the agent tests: fake knowledge base and orders clients, and chat models."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import agent
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from orders_client import OrderNotFoundError
from rag_client import Passage

FAKE_ANSWER = "Yes, the argan shampoo suits curly hair."
FAKE_GENERAL_REPLY = (
    "Hello! I can help with questions about our hair care products, and with orders "
    "and refunds."
)

FAKE_PASSAGES: list[Passage] = [
    {"passage": "Argan shampoo is gentle on curls.", "source": "s3://kb/knowledge_base/argan_shampoo.md", "score": 0.9},
    {"passage": "Use it two or three times a week.", "source": "s3://kb/knowledge_base/argan_shampoo.md", "score": 0.8},
    {"passage": "Curly hair needs moisture.", "source": "s3://kb/knowledge_base/hair_type_guide.md", "score": 0.7},
]

# The product reply the fakes produce: answer plus de-duplicated sources.
FAKE_PRODUCT_REPLY = f"{FAKE_ANSWER}\n\nSources: argan_shampoo.md, hair_type_guide.md"


@dataclass
class FakeRagClient:
    """Stands in for rag_client.RagClient. Records each search call."""

    passages: list[Passage] = field(default_factory=lambda: list(FAKE_PASSAGES))
    error: Exception | None = None
    calls: list[tuple[str, int]] = field(default_factory=list)

    def search(self, query: str, top_k: int) -> list[Passage]:
        self.calls.append((query, top_k))
        if self.error is not None:
            raise self.error
        return self.passages


@dataclass
class FakeProduct:
    """Handles to the fakes installed by the `fake_product` fixture."""

    rag: FakeRagClient
    model: FakeListChatModel


@pytest.fixture
def fake_product(monkeypatch) -> FakeProduct:
    """Replace the product node's knowledge base client and model with fakes."""
    rag = FakeRagClient()
    model = FakeListChatModel(responses=[FAKE_ANSWER])
    monkeypatch.setattr(agent, "_rag_client", lambda: rag)
    monkeypatch.setattr(agent, "_product_model", lambda: model)
    return FakeProduct(rag=rag, model=model)


@dataclass
class FakeGeneralModel:
    """Stands in for the general node's model. Records the messages of each call."""

    reply: str = FAKE_GENERAL_REPLY
    error: Exception | None = None
    calls: list[list[AnyMessage]] = field(default_factory=list)

    def invoke(self, messages: Sequence[AnyMessage]) -> AIMessage:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        return AIMessage(self.reply)


@pytest.fixture
def fake_general(monkeypatch) -> FakeGeneralModel:
    """Replace the general node's model with a fake."""
    model = FakeGeneralModel()
    monkeypatch.setattr(agent, "_general_model", lambda: model)
    return model


# --- Refunds -----------------------------------------------------------------

FAKE_REFUND_REPLY = "Your order AC-1001 was delivered."

# Mirrors data/orders/orders.json, with the dates resolved as the orders API does.
FAKE_ORDERS: dict[str, dict[str, Any]] = {
    "AC-1001": {
        "order_number": "AC-1001",
        "customer_name": "Jordan Lee",
        "email": "jordan@example.com",
        "items": [{"product": "Weekly Repair Mask", "qty": 1, "price": 30}],
        "status": "delivered",
        "refund_status": None,
        "purchased_days_ago": 12,
        "purchased": "2026-11-15",
    },
    "AC-1002": {
        "order_number": "AC-1002",
        "customer_name": "Priya Shah",
        "email": "priya@example.com",
        "items": [{"product": "Repair Bond Oil", "qty": 2, "price": 32}],
        "status": "delivered",
        "refund_status": None,
        "purchased_days_ago": 120,
        "purchased": "2026-07-30",
    },
    "AC-1003": {
        "order_number": "AC-1003",
        "customer_name": "Alex Rivera",
        "email": "alex@example.com",
        "items": [
            {"product": "Hydra Wash Shampoo", "qty": 1, "price": 22},
            {"product": "Silk Slip Conditioner", "qty": 1, "price": 23},
        ],
        "status": "delivered",
        "refund_status": "refunded",
        "purchased_days_ago": 200,
        "purchased": "2026-05-11",
    },
}

FAKE_POLICIES: dict[str, dict[str, Any]] = {
    "AC-1001": {"eligible": True, "reason": "Order is eligible for a refund.", "days_since_purchase": 12, "window_days": 30},
    "AC-1002": {"eligible": False, "reason": "The 30-day return window has passed (120 days since purchase).", "days_since_purchase": 120, "window_days": 30},
    "AC-1003": {"eligible": False, "reason": "This order has already been refunded.", "days_since_purchase": 200, "window_days": 30},
}


@dataclass
class FakeOrdersClient:
    """Stands in for orders_client.OrdersClient. Records each (tool, order_number) call."""

    error: Exception | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def _order(self, tool: str, order_number: str) -> dict[str, Any]:
        self.calls.append((tool, order_number))
        if self.error is not None:
            raise self.error
        if order_number not in FAKE_ORDERS:
            raise OrderNotFoundError(f"Order {order_number} not found")
        return FAKE_ORDERS[order_number]

    def get_order(self, order_number: str) -> dict[str, Any]:
        return dict(self._order("get_order", order_number))

    def return_policy(self, order_number: str) -> dict[str, Any]:
        # The real API reports an unknown order as ineligible, not as an error.
        self.calls.append(("return_policy", order_number))
        if self.error is not None:
            raise self.error
        return dict(
            FAKE_POLICIES.get(
                order_number,
                {"eligible": False, "reason": "Order not found.", "days_since_purchase": 0, "window_days": 30},
            )
        )

    def refund_status(self, order_number: str) -> dict[str, Any]:
        order = self._order("refund_status", order_number)
        return {"order_number": order_number, "refund_status": order["refund_status"]}

    def refund_amount(self, order_number: str) -> dict[str, Any]:
        order = self._order("refund_amount", order_number)
        amount = sum(i["price"] * i["qty"] for i in order["items"])
        return {"order_number": order_number, "refund_amount": amount}


def tool_call(name: str, call_id: str = "call-1", **args: Any) -> AIMessage:
    """A scripted model turn that calls one tool."""
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


@dataclass
class FakeRefundsModel:
    """Stands in for the refunds model. Plays scripted turns and records each call.

    `script` is the sequence of AIMessages to return, one per call (tool calls
    included). When it runs out, the model answers FAKE_REFUND_REPLY.
    """

    script: list[AIMessage] = field(default_factory=list)
    error: Exception | None = None
    calls: list[list[BaseMessage]] = field(default_factory=list)
    bound_tools: list[Any] = field(default_factory=list)

    def bind_tools(self, tools: Sequence[Any]) -> "FakeRefundsModel":
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        if self.script:
            return self.script.pop(0)
        return AIMessage(FAKE_REFUND_REPLY)


@dataclass
class FakeRefunds:
    """Handles to the fakes installed by the `fake_refunds` fixture."""

    orders: FakeOrdersClient
    model: FakeRefundsModel


@pytest.fixture
def fake_refunds(monkeypatch) -> FakeRefunds:
    """Replace the refunds node's orders client and model with fakes."""
    orders = FakeOrdersClient()
    model = FakeRefundsModel()
    monkeypatch.setattr(agent, "_orders_client", lambda: orders)
    monkeypatch.setattr(agent, "_refunds_model", lambda: model)
    return FakeRefunds(orders=orders, model=model)


# --- Router ------------------------------------------------------------------


@pytest.fixture
def fake_router(monkeypatch):
    """Return a setter that makes the router return fixed intents, with no model call."""

    def set_intents(intents: list[str]) -> None:
        decision = agent.RouterDecision.model_validate({"intents": intents})
        monkeypatch.setattr(agent, "_router_model", lambda: RunnableLambda(lambda _: decision))

    return set_intents

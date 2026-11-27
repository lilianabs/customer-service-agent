"""Shared fakes for the agent tests: a fake knowledge base client and chat models."""

from collections.abc import Sequence
from dataclasses import dataclass, field

import agent
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableLambda
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


@pytest.fixture
def fake_router(monkeypatch):
    """Return a setter that makes the router return fixed intents, with no model call."""

    def set_intents(intents: list[str]) -> None:
        decision = agent.RouterDecision.model_validate({"intents": intents})
        monkeypatch.setattr(agent, "_router_model", lambda: RunnableLambda(lambda _: decision))

    return set_intents

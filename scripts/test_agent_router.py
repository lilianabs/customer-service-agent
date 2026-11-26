"""
Smoke test for the intent router graph in services/agents/agent.py.

Checks, in order:
  1. Routing logic (no model call): next_step and normalize_intents.
  2. Live routing (calls amazon.nova-micro-v1:0 on Bedrock): each sample message
     is sent through run_turn and the reply is checked against the expected branch.
  3. Memory: a follow-up on the same thread_id keeps the earlier turn in history.

Needs AWS credentials with Bedrock access in AWS_REGION (default us-east-1).

Run from the project root:
    uv run python scripts/test_agent_router.py

Exit code 0 means all checks passed.
"""

import sys
import uuid
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / "services" / "agents"
sys.path.insert(0, str(AGENTS_DIR))

import agent
from langgraph.graph import END

PRODUCT_REPLY = "[product questions agent not built yet]"
REFUND_REPLY = "[refunds agent not built yet]"
OTHER_REPLY = agent.OUT_OF_SCOPE_REPLY

# (message, expected replies in order)
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


def check_routing_logic() -> list[str]:
    failures = []

    def expect(label, actual, expected):
        if actual != expected:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    expect("next_step product first",
           agent.next_step({"pending_intents": ["product", "refund"]}), "product_questions")
    expect("next_step refund",
           agent.next_step({"pending_intents": ["refund"]}), "refunds")
    expect("next_step other",
           agent.next_step({"pending_intents": ["other"]}), "out_of_scope")
    expect("next_step empty ends the run",
           agent.next_step({"pending_intents": []}), END)
    expect("normalize dedupes and keeps order",
           agent.normalize_intents(["refund", "product", "refund"]), ["refund", "product"])
    expect("normalize drops other next to a real intent",
           agent.normalize_intents(["refund", "other"]), ["refund"])
    expect("normalize empty falls back to other",
           agent.normalize_intents([]), ["other"])
    return failures


def check_live_routing() -> list[str]:
    failures = []
    for message, expected in LIVE_CASES:
        thread_id = f"test-{uuid.uuid4()}"
        reply = agent.run_turn(message, thread_id)["reply"]
        expected_reply = "\n\n".join(expected)
        mark = "✅" if reply == expected_reply else "❌"
        print(f"{mark} {message!r} -> {reply!r}")
        if reply != expected_reply:
            failures.append(f"{message!r}: expected {expected_reply!r}, got {reply!r}")
    return failures


def check_memory() -> list[str]:
    failures = []
    thread_id = f"test-{uuid.uuid4()}"
    agent.run_turn("Does the argan shampoo work on curly hair?", thread_id)
    agent.run_turn("And how often should I use it?", thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    messages = agent.graph.get_state(config).values["messages"]
    # Two user turns and two replies from the first turns, plus the second turn's user
    # message and reply: 4 messages from the first turn's history are still present.
    mark = "✅" if len(messages) == 4 else "❌"
    print(f"{mark} follow-up keeps history: {len(messages)} messages on thread")
    if len(messages) != 4:
        failures.append(f"memory: expected 4 messages on thread, got {len(messages)}")
    return failures


def main() -> int:
    print("== Routing logic (no model call)")
    failures = check_routing_logic()
    print(("✅" if not failures else "❌") + " routing logic")

    print("\n== Live routing (Bedrock, amazon.nova-micro-v1:0)")
    failures += check_live_routing()

    print("\n== Memory on one thread_id")
    failures += check_memory()

    print()
    if failures:
        print(f"❌ {len(failures)} check(s) failed:")
        for failure in failures:
            print(f"  ❌ {failure}")
        return 1
    print("✅ All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

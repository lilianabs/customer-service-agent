#!/bin/bash
# Smoke test for the deployed MCP server (AgentCore Runtime).
#
# Usage: ./scripts/smoke_test_mcp.sh
# Runs `agentcore invoke` from services/mcp-server, which reads the deployment
# configuration (.bedrock_agentcore.yaml) from that directory.
#
# The checks are read-only: they list tools and call read tools only.

set -u

export AGENTCORE_SUPPRESS_RECOMMENDATION=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MCP_SERVER_DIR="$PROJECT_ROOT/services/mcp-server"

cd "$MCP_SERVER_DIR" || exit 2

PASS=0
FAIL=0

# invoke <json-rpc payload> : prints the agentcore output, or nothing on failure
invoke() {
  uv run agentcore invoke "$1" 2>&1
}

# check <description> <payload> <grep -E pattern that must match the output>
check() {
  local desc="$1" payload="$2" pattern="$3" out
  out=$(invoke "$payload")
  if echo "$out" | grep -E -q "$pattern"; then
    echo "ok    $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $desc: output did not match: $pattern"
    echo "      $out"
    FAIL=$((FAIL + 1))
  fi
}

echo "Smoke testing the MCP server in $MCP_SERVER_DIR"
echo

TOOLS_LIST='{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
TOOLS_OUT=$(invoke "$TOOLS_LIST")

for tool in get_order return_policy refund_status refund_amount apply_refund get_product_inventory search_product_information; do
  if echo "$TOOLS_OUT" | grep -q "\"$tool\""; then
    echo "ok    tools/list includes $tool"
    PASS=$((PASS + 1))
  else
    echo "FAIL  tools/list is missing $tool"
    FAIL=$((FAIL + 1))
  fi
done

if echo "$TOOLS_OUT" | grep -q "roll_d20"; then
  echo "FAIL  tools/list still includes the roll_d20 scaffold tool"
  FAIL=$((FAIL + 1))
else
  echo "ok    tools/list does not include roll_d20"
  PASS=$((PASS + 1))
fi

# Proves ORDERS_API_URL reaches the deployed server and the orders API answers.
check "return_policy calls the orders API" \
  '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "return_policy", "arguments": {"order_number": "AC-1001"}}}' \
  'eligible.*true'

# The refund tools return dicts; a wrong return annotation fails output validation.
check "refund_status returns the order's refund status" \
  '{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "refund_status", "arguments": {"order_number": "AC-1001"}}}' \
  'refund_status'

check "refund_amount returns the order's refund amount" \
  '{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "refund_amount", "arguments": {"order_number": "AC-1001"}}}' \
  'refund_amount[^0-9]*30'

# Proves RAG_V0_KB_ID and the runtime role's bedrock:Retrieve permission work.
check "search_product_information returns passages" \
  '{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_product_information", "arguments": {"query": "how often should I wash my hair", "top_k": 3}}}' \
  'passage'

echo
echo "Passed: $PASS, Failed: $FAIL"
[ "$FAIL" -eq 0 ]

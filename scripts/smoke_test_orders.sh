#!/bin/bash
# Smoke test for the deployed orders API (API Gateway + Lambda).
#
# Usage: ./scripts/smoke_test_orders.sh [BASE_URL]
# BASE_URL defaults to `terraform output base_url` of infra/modules/orders.
#
# The checks are idempotent: they only read data, plus an apply_refund on an
# order that is already refunded (a no-op), so the script can be re-run.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

BASE_URL="${1:-$(terraform -chdir="$PROJECT_ROOT/infra/modules/orders" output -raw base_url 2>/dev/null)}"
BASE_URL="${BASE_URL%/}"

if [ -z "$BASE_URL" ]; then
  echo "Could not determine the API base URL. Pass it as an argument or deploy the orders module first." >&2
  exit 2
fi

echo "Smoke testing $BASE_URL"
echo

PASS=0
FAIL=0

# check <description> <method> <path> <expected status> <jq filter that must be true>
check() {
  local desc="$1" method="$2" path="$3" expected="$4" filter="${5:-}"
  local out status body
  out=$(curl -s -X "$method" -w $'\n%{http_code}' "$BASE_URL$path")
  status="${out##*$'\n'}"
  body="${out%$'\n'*}"

  if [ "$status" != "$expected" ]; then
    echo "FAIL  $desc ($method $path): expected HTTP $expected, got $status"
    echo "      $body"
    FAIL=$((FAIL + 1))
    return
  fi
  if [ -n "$filter" ] && ! echo "$body" | jq -e "$filter" >/dev/null 2>&1; then
    echo "FAIL  $desc ($method $path): body did not satisfy: $filter"
    echo "      $body"
    FAIL=$((FAIL + 1))
    return
  fi
  echo "ok    $desc"
  PASS=$((PASS + 1))
}

# AC-1001: delivered, recent, not refunded   AC-1002: delivered, outside window
# AC-1003: already refunded                  WRM-001: in-stock product
check "get_order"                       GET  /orders/AC-1001                 200 '.order_number == "AC-1001" and (.items | length) > 0'
check "get_order (unknown order)"       GET  /orders/NOPE                    404
check "return_policy (eligible)"        GET  /orders/AC-1001/return-policy   200 '.eligible == true and .window_days == 30'
check "return_policy (window passed)"   GET  /orders/AC-1002/return-policy   200 '.eligible == false'
check "return_policy (already refunded)" GET /orders/AC-1003/return-policy   200 '.eligible == false'
check "return_policy (unknown order)"   GET  /orders/NOPE/return-policy      200 '.eligible == false'
check "refund_amount"                   GET  /orders/AC-1001/refund-amount   200 '.refund_amount == 30'
check "refund_amount (unknown order)"   GET  /orders/NOPE/refund-amount      404
check "refund_status (not refunded)"    GET  /orders/AC-1001/refund-status   200 '.refund_status == null'
check "refund_status (refunded)"        GET  /orders/AC-1003/refund-status   200 '.refund_status == "refunded"'
check "refund_status (unknown order)"   GET  /orders/NOPE/refund-status      404
check "apply_refund (already refunded, no-op)" POST /orders/AC-1003/refund   200 '.success == true'
check "apply_refund (unknown order)"    POST /orders/NOPE/refund             404
check "get_product_inventory"           GET  /inventory/WRM-001              200 '.code == "WRM-001" and .qty >= 0'
check "get_product_inventory (unknown)" GET  /inventory/NOPE                 404

echo
echo "Passed: $PASS, Failed: $FAIL"
[ "$FAIL" -eq 0 ]

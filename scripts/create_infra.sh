#!/bin/bash
# Create infrastructure resources for the orders service and the RAG v0 knowledge base:
#   1. the S3 bucket holding the orders data (with the data uploaded)
#   2. the orders module (Lambda + API Gateway) via Terraform
#   3. a smoke test against the deployed orders API
#   4. the RAG v0 knowledge base (S3 bucket + managed Bedrock KB)
#   5. a smoke test against the RAG v0 knowledge base
#   6. the MCP server on AgentCore Runtime (needs the orders API and the KB)
#   7. a smoke test against the MCP server

set -e

export AGENTCORE_SUPPRESS_RECOMMENDATION=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config.json"
ORDERS_MODULE_DIR="$PROJECT_ROOT/infra/modules/orders"
MCP_SERVER_DIR="$PROJECT_ROOT/services/mcp-server"

# Load configuration from config.json
BUCKET_NAME=$(jq -r '.orders.bucket_name' "$CONFIG_FILE")
AWS_REGION=$(jq -r '.aws.region' "$CONFIG_FILE")
ORDERS_DATA_PATH=$(jq -r '.orders.data_path' "$CONFIG_FILE")

echo "Creating infrastructure..."
echo "Bucket name: $BUCKET_NAME"
echo "Region: $AWS_REGION"

# Create S3 bucket (skipped if it already exists)
if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null; then
  echo "S3 bucket $BUCKET_NAME already exists, skipping creation"
else
  echo "Creating S3 bucket: $BUCKET_NAME"
  aws s3 mb "s3://$BUCKET_NAME" --region "$AWS_REGION"
fi

# Upload orders data (overwrites any existing copy)
echo "Uploading orders data..."
aws s3 cp "$PROJECT_ROOT/$ORDERS_DATA_PATH" "s3://$BUCKET_NAME/" --region "$AWS_REGION"

# Deploy the orders module (Lambda + API Gateway)
echo "Deploying orders module..."
terraform -chdir="$ORDERS_MODULE_DIR" init -input=false
terraform -chdir="$ORDERS_MODULE_DIR" apply -input=false -auto-approve \
  -var "aws_region=$AWS_REGION" \
  -var "orders_bucket_name=$BUCKET_NAME" \
  -var "orders_data_key=$(basename "$ORDERS_DATA_PATH")"

# API Gateway can answer "Not Found" for a few seconds after a fresh deploy, even
# when the routes exist. Wait until a known order is served before smoke testing.
echo "Waiting for the orders API to become ready..."
ORDERS_BASE_URL=$(terraform -chdir="$ORDERS_MODULE_DIR" output -raw base_url)
for _ in $(seq 1 24); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$ORDERS_BASE_URL/orders/AC-1001")" = "200" ]; then
    break
  fi
  sleep 5
done

# Smoke test the deployed API
echo "Running smoke tests..."
"$SCRIPT_DIR/smoke_test_orders.sh"

# Create the RAG v0 knowledge base (S3 bucket + managed Bedrock KB).
# Writes the bucket name and KB ID to config.json.
echo "Creating RAG v0 knowledge base..."
"$PROJECT_ROOT/infra/modules/rag_v0/create_kb_infra.sh"

# Smoke test the RAG v0 knowledge base (reads the KB ID saved in config.json)
echo "Running RAG v0 smoke tests..."
if command -v uv >/dev/null 2>&1; then
  (cd "$PROJECT_ROOT" && uv run python scripts/smoke_test_kb_v0.py)
else
  python3 "$SCRIPT_DIR/smoke_test_kb_v0.py"
fi

# Deploy the MCP server to AgentCore Runtime. It needs the orders API URL and
# the KB ID, so it runs after both exist.
echo "Deploying MCP server..."
ORDERS_API_URL=$(terraform -chdir="$ORDERS_MODULE_DIR" output -raw base_url)
KB_ID=$(jq -r '.rag_v0.kb_id // ""' "$CONFIG_FILE")
if [ -z "$ORDERS_API_URL" ] || [ -z "$KB_ID" ]; then
  echo "Cannot deploy the MCP server: ORDERS_API_URL or rag_v0.kb_id in config.json is empty." >&2
  exit 1
fi

cd "$MCP_SERVER_DIR"

# Configure once. The configuration file is the marker for "already configured",
# so re-runs skip this step.
if [ ! -f .bedrock_agentcore.yaml ]; then
  echo "Configuring AgentCore for the MCP server..."
  uv run agentcore configure \
    --entrypoint server.py \
    --requirements-file pyproject.toml \
    --protocol MCP \
    --deployment-type direct_code_deploy \
    --name mcp_server_hair_care \
    --region "$AWS_REGION" \
    --non-interactive
fi

# Deploy or update the runtime. --auto-update-on-conflict makes re-runs update
# the existing runtime instead of failing.
echo "Deploying MCP server to AgentCore..."
uv run agentcore deploy \
  --auto-update-on-conflict \
  --env "ORDERS_API_URL=$ORDERS_API_URL" \
  --env "RAG_V0_KB_ID=$KB_ID" \
  --env "AWS_REGION=$AWS_REGION"

# Let the runtime's execution role call the KB. Without this, deploy succeeds
# but search_product_information fails with AccessDenied when called.
ROLE_ARN=$(uv run python -c "import yaml; c = yaml.safe_load(open('.bedrock_agentcore.yaml')); print(c['agents'][c['default_agent']]['aws']['execution_role'])")
ROLE_NAME="${ROLE_ARN##*/}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name mcp-server-kb-retrieve \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"bedrock:Retrieve\",\"Resource\":\"arn:aws:bedrock:$AWS_REGION:$ACCOUNT_ID:knowledge-base/$KB_ID\"}]}"

# Save the MCP runtime ARN for the agents (rag_client reads mcp.runtime_arn).
MCP_RUNTIME_ARN=$(uv run python -c "import yaml; c = yaml.safe_load(open('.bedrock_agentcore.yaml')); print(c['agents'][c['default_agent']]['bedrock_agentcore']['agent_arn'] or '')")
AGENTS_CONFIG_FILE="$PROJECT_ROOT/services/agents/config.json"
tmp=$(mktemp)
jq --arg arn "$MCP_RUNTIME_ARN" '.mcp.runtime_arn = $arn' "$AGENTS_CONFIG_FILE" > "$tmp" && mv "$tmp" "$AGENTS_CONFIG_FILE"
echo "MCP runtime ARN: $MCP_RUNTIME_ARN (saved to services/agents/config.json as mcp.runtime_arn)"

cd "$PROJECT_ROOT"

# Smoke test the deployed MCP server
echo "Running MCP server smoke tests..."
"$SCRIPT_DIR/smoke_test_mcp.sh"

echo "✓ Infrastructure created successfully"

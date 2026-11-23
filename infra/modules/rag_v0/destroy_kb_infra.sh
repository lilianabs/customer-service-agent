#!/bin/bash
# Destroy the RAG v0 knowledge base created by create_kb_infra.sh:
#   1. the data source and the knowledge base
#   2. the IAM role used by the knowledge base
#   3. the S3 bucket holding the knowledge base files
#
# Every step tolerates resources that are already gone, so a partly created
# setup can be cleaned up too. Set SKIP_CONFIRM=1 to skip the confirmation
# (scripts/destroy_infra.sh does this after asking once itself).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"
CONFIG_FILE="$PROJECT_ROOT/config.json"

ROLE_NAME="rag-v0-kb-role"
POLICY_NAME="rag-v0-kb-data-read"

AWS_REGION=$(jq -r '.aws.region' "$CONFIG_FILE")
BUCKET_NAME=$(jq -r '.rag_v0.bucket_name // ""' "$CONFIG_FILE")
KB_ID=$(jq -r '.rag_v0.kb_id // ""' "$CONFIG_FILE")
DATA_SOURCE_ID=$(jq -r '.rag_v0.data_source_id // ""' "$CONFIG_FILE")

if ! aws bedrock-agent help >/dev/null 2>&1; then
  echo "Your AWS CLI ($(aws --version 2>&1)) does not support 'aws bedrock-agent'. Upgrade to the latest AWS CLI v2." >&2
  exit 1
fi

echo "Destroying RAG v0 knowledge base..."
echo "Bucket name: ${BUCKET_NAME:-<none>}"
echo "Knowledge base ID: ${KB_ID:-<none>}"

if [ "${SKIP_CONFIRM:-}" != "1" ]; then
  read -p "⚠️  This will delete the knowledge base, its IAM role, and the S3 bucket '$BUCKET_NAME' with all its contents. Continue? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
  fi
fi

# --- 1. Data source and knowledge base ---
if [ -n "$KB_ID" ] && aws bedrock-agent get-knowledge-base --knowledge-base-id "$KB_ID" \
    --region "$AWS_REGION" >/dev/null 2>&1; then
  if [ -n "$DATA_SOURCE_ID" ]; then
    echo "Deleting data source: $DATA_SOURCE_ID"
    aws bedrock-agent delete-data-source --knowledge-base-id "$KB_ID" \
      --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" >/dev/null 2>&1 || true

    # The knowledge base can only be deleted after its data source is gone
    while aws bedrock-agent get-data-source --knowledge-base-id "$KB_ID" \
        --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" >/dev/null 2>&1; do
      sleep 5
    done
  fi

  echo "Deleting knowledge base: $KB_ID"
  aws bedrock-agent delete-knowledge-base --knowledge-base-id "$KB_ID" \
    --region "$AWS_REGION" >/dev/null

  while aws bedrock-agent get-knowledge-base --knowledge-base-id "$KB_ID" \
      --region "$AWS_REGION" >/dev/null 2>&1; do
    sleep 5
  done
else
  echo "No knowledge base found, skipping"
fi

# --- 2. IAM role ---
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Deleting IAM role: $ROLE_NAME"
  aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY_NAME" 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_NAME"
else
  echo "IAM role $ROLE_NAME not found, skipping"
fi

# --- 3. S3 bucket ---
if [ -n "$BUCKET_NAME" ] && aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null; then
  echo "Removing S3 bucket: $BUCKET_NAME"
  aws s3 rb "s3://$BUCKET_NAME" --force --region "$AWS_REGION"
else
  echo "S3 bucket not found, skipping"
fi

# Clear the saved names and IDs
tmp=$(mktemp)
jq '.rag_v0 = {bucket_name: "", kb_id: "", data_source_id: ""}' "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"

echo "✓ RAG v0 knowledge base destroyed successfully"

#!/bin/bash
# Destroy infrastructure resources for the RAG v0 knowledge base and the orders service:
#   1. the RAG v0 knowledge base (KB, IAM role, S3 bucket)
#   2. the orders module (Lambda + API Gateway) via Terraform
#   3. the S3 bucket holding the orders data

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config.json"
ORDERS_MODULE_DIR="$PROJECT_ROOT/infra/modules/orders"

# Load configuration from config.json
BUCKET_NAME=$(jq -r '.orders.bucket_name' "$CONFIG_FILE")
AWS_REGION=$(jq -r '.aws.region' "$CONFIG_FILE")
ORDERS_DATA_PATH=$(jq -r '.orders.data_path' "$CONFIG_FILE")

echo "Destroying infrastructure..."
echo "Bucket name: $BUCKET_NAME"

# Confirm before destroying
read -p "⚠️  This will destroy the orders Lambda and API Gateway, the RAG v0 knowledge base (with its IAM role and S3 bucket), and delete the S3 bucket '$BUCKET_NAME' and all its contents. Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 1
fi

# Destroy the RAG v0 knowledge base first (KB, IAM role, its S3 bucket).
# SKIP_CONFIRM=1 because the single prompt above already covers it.
echo "Destroying RAG v0 knowledge base..."
SKIP_CONFIRM=1 "$PROJECT_ROOT/infra/modules/rag_v0/destroy_kb_infra.sh"

# Destroy the orders module (Lambda + API Gateway) while the orders bucket
# it reads from still exists. The same -var values as create_infra.sh are
# passed so the IAM policy and variables resolve identically.
echo "Destroying orders module..."
terraform -chdir="$ORDERS_MODULE_DIR" init -input=false
terraform -chdir="$ORDERS_MODULE_DIR" destroy -input=false -auto-approve \
  -var "aws_region=$AWS_REGION" \
  -var "orders_bucket_name=$BUCKET_NAME" \
  -var "orders_data_key=$(basename "$ORDERS_DATA_PATH")"

# Remove S3 bucket and contents
echo "Removing S3 bucket: $BUCKET_NAME"
aws s3 rb "s3://$BUCKET_NAME" --force --region "$AWS_REGION"

echo "✓ Infrastructure destroyed successfully"

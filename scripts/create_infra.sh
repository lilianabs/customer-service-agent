#!/bin/bash
# Create infrastructure resources for the orders service:
#   1. the S3 bucket holding the orders data (with the data uploaded)
#   2. the orders module (Lambda + API Gateway) via Terraform
#   3. a smoke test against the deployed API

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config.json"
ORDERS_MODULE_DIR="$PROJECT_ROOT/infra/modules/orders"

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

# Smoke test the deployed API
echo "Running smoke tests..."
"$SCRIPT_DIR/smoke_test_orders.sh"

echo "✓ Infrastructure created successfully"

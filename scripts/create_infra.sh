#!/bin/bash
# Create infrastructure resources for the orders service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config.json"

# Load configuration from config.json
BUCKET_NAME=$(jq -r '.orders.bucket_name' "$CONFIG_FILE")
AWS_REGION=$(jq -r '.aws.region' "$CONFIG_FILE")
ORDERS_DATA_PATH=$(jq -r '.orders.data_path' "$CONFIG_FILE")

echo "Creating infrastructure..."
echo "Bucket name: $BUCKET_NAME"
echo "Region: $AWS_REGION"

# Create S3 bucket
echo "Creating S3 bucket: $BUCKET_NAME"
aws s3 mb "s3://$BUCKET_NAME" --region "$AWS_REGION"

# Upload orders data
echo "Uploading orders data..."
aws s3 cp "$PROJECT_ROOT/$ORDERS_DATA_PATH" "s3://$BUCKET_NAME/" --region "$AWS_REGION"

echo "✓ Infrastructure created successfully"

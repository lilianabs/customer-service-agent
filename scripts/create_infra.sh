#!/bin/bash
# Create infrastructure resources for the orders service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Source global configuration
source "$SCRIPT_DIR/config.sh"

echo "Creating infrastructure..."
echo "Bucket name: $ORDERS_BUCKET_NAME"
echo "Region: $AWS_REGION"

# Create S3 bucket
echo "Creating S3 bucket: $ORDERS_BUCKET_NAME"
aws s3 mb "s3://$ORDERS_BUCKET_NAME" --region "$AWS_REGION"

# Upload orders data
echo "Uploading orders data..."
aws s3 cp "$PROJECT_ROOT/$ORDERS_DATA_PATH" "s3://$ORDERS_BUCKET_NAME/" --region "$AWS_REGION"

echo "✓ Infrastructure created successfully"

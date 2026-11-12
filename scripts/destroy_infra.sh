#!/bin/bash
# Destroy infrastructure resources for the orders service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source global configuration
source "$SCRIPT_DIR/config.sh"

echo "Destroying infrastructure..."
echo "Bucket name: $ORDERS_BUCKET_NAME"

# Confirm before destroying
read -p "⚠️  This will delete the S3 bucket '$ORDERS_BUCKET_NAME' and all its contents. Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 1
fi

# Remove S3 bucket and contents
echo "Removing S3 bucket: $ORDERS_BUCKET_NAME"
aws s3 rb "s3://$ORDERS_BUCKET_NAME" --force --region "$AWS_REGION"

echo "✓ Infrastructure destroyed successfully"

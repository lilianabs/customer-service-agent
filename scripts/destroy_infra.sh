#!/bin/bash
# Destroy infrastructure resources for the orders service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_FILE="$PROJECT_ROOT/config.json"

# Load configuration from config.json
BUCKET_NAME=$(jq -r '.orders.bucket_name' "$CONFIG_FILE")
AWS_REGION=$(jq -r '.aws.region' "$CONFIG_FILE")

echo "Destroying infrastructure..."
echo "Bucket name: $BUCKET_NAME"

# Confirm before destroying
read -p "⚠️  This will delete the S3 bucket '$BUCKET_NAME' and all its contents. Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 1
fi

# Remove S3 bucket and contents
echo "Removing S3 bucket: $BUCKET_NAME"
aws s3 rb "s3://$BUCKET_NAME" --force --region "$AWS_REGION"

echo "✓ Infrastructure destroyed successfully"

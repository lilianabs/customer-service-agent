#!/bin/bash
# Create the RAG v0 knowledge base (managed Amazon Bedrock Knowledge Base with
# out-of-the-box settings), as explored in notebooks/03_rag_v0_exploration.ipynb:
#   1. a private S3 bucket holding the knowledge base Markdown files
#   2. the files from data/knowledge-base/ uploaded to it
#   3. an IAM role Bedrock uses to read the bucket
#   4. the managed knowledge base, its S3 data source and a first ingestion job
#
# Generated names and IDs are written to the "rag_v0" section of config.json,
# so re-running the script reuses what already exists.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"
CONFIG_FILE="$PROJECT_ROOT/config.json"
KB_DIR="$PROJECT_ROOT/data/knowledge-base"

BUCKET_PREFIX="product-information-kb-data"
KB_PREFIX="knowledge_base/"
ROLE_NAME="rag-v0-kb-role"
POLICY_NAME="rag-v0-kb-data-read"
KB_NAME="rag-v0"
DATA_SOURCE_NAME="product-information"

AWS_REGION=$(jq -r '.aws.region' "$CONFIG_FILE")
BUCKET_NAME=$(jq -r '.rag_v0.bucket_name // ""' "$CONFIG_FILE")
KB_ID=$(jq -r '.rag_v0.kb_id // ""' "$CONFIG_FILE")
DATA_SOURCE_ID=$(jq -r '.rag_v0.data_source_id // ""' "$CONFIG_FILE")

# Write one key of the rag_v0 section in config.json
set_config() {
  local tmp
  tmp=$(mktemp)
  jq --arg v "$2" ".rag_v0.$1 = \$v" "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
}

# The Bedrock agent commands need a recent AWS CLI v2
if ! aws bedrock-agent help >/dev/null 2>&1; then
  echo "Your AWS CLI ($(aws --version 2>&1)) does not support 'aws bedrock-agent'. Upgrade to the latest AWS CLI v2." >&2
  exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "Creating RAG v0 knowledge base..."
echo "Region: $AWS_REGION"

# --- 1. S3 bucket ---
if [ -z "$BUCKET_NAME" ]; then
  # Bucket names are global, so a random suffix is added
  BUCKET_NAME="$BUCKET_PREFIX-$(openssl rand -hex 4)"
  set_config bucket_name "$BUCKET_NAME"
fi

if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null; then
  echo "S3 bucket $BUCKET_NAME already exists, skipping creation"
else
  echo "Creating S3 bucket: $BUCKET_NAME"
  # us-east-1 rejects a LocationConstraint; every other region requires it
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" \
      --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
  fi
  # A new bucket can take a moment to become visible to every S3 call
  aws s3api wait bucket-exists --bucket "$BUCKET_NAME" --region "$AWS_REGION"
fi

aws s3api put-public-access-block --bucket "$BUCKET_NAME" --region "$AWS_REGION" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# --- 2. Upload the knowledge base files (only Markdown, only new or changed) ---
echo "Uploading knowledge base files..."
aws s3 sync "$KB_DIR" "s3://$BUCKET_NAME/$KB_PREFIX" \
  --exclude "*" --include "*.md" --region "$AWS_REGION" >/dev/null

LOCAL_COUNT=$(find "$KB_DIR" -name "*.md" | wc -l | tr -d ' ')
# The listing can briefly lag behind the upload, so retry a few times
REMOTE_COUNT=0
for attempt in 1 2 3 4 5; do
  REMOTE_COUNT=$(aws s3 ls "s3://$BUCKET_NAME/$KB_PREFIX" --recursive --region "$AWS_REGION" 2>/dev/null | wc -l | tr -d ' ')
  [ "$LOCAL_COUNT" = "$REMOTE_COUNT" ] && break
  sleep 3
done
echo "Local .md files: $LOCAL_COUNT, objects in bucket: $REMOTE_COUNT"
if [ "$LOCAL_COUNT" != "$REMOTE_COUNT" ]; then
  echo "Upload verification failed: file counts differ" >&2
  exit 1
fi

# --- 3. IAM role for the knowledge base ---
TRUST_POLICY=$(jq -n --arg account "$ACCOUNT_ID" '{
  Version: "2012-10-17",
  Statement: [{
    Effect: "Allow",
    Principal: {Service: "bedrock.amazonaws.com"},
    Action: "sts:AssumeRole",
    Condition: {StringEquals: {"aws:SourceAccount": $account}}
  }]
}')

ROLE_POLICY=$(jq -n --arg bucket "$BUCKET_NAME" '{
  Version: "2012-10-17",
  Statement: [
    {Effect: "Allow", Action: "s3:ListBucket", Resource: "arn:aws:s3:::\($bucket)"},
    {Effect: "Allow", Action: "s3:GetObject", Resource: "arn:aws:s3:::\($bucket)/*"}
  ]
}')

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "IAM role $ROLE_NAME already exists, skipping creation"
else
  echo "Creating IAM role: $ROLE_NAME"
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" >/dev/null
  echo "Waiting for the IAM role to propagate..."
  sleep 10
fi
# put-role-policy overwrites, so the bucket name stays current
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY_NAME" \
  --policy-document "$ROLE_POLICY"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)

# --- 4. Managed knowledge base ---
# If config.json has no (valid) KB ID, adopt an existing KB with the same name,
# for example one left by an earlier run that stopped before saving its ID.
if [ -z "$KB_ID" ] || ! aws bedrock-agent get-knowledge-base --knowledge-base-id "$KB_ID" \
    --region "$AWS_REGION" >/dev/null 2>&1; then
  KB_ID=$(aws bedrock-agent list-knowledge-bases --region "$AWS_REGION" \
    --query "knowledgeBaseSummaries[?name=='$KB_NAME'].knowledgeBaseId | [0]" --output text)
  if [ "$KB_ID" = "None" ]; then
    KB_ID=""
  else
    echo "Found existing knowledge base $KB_NAME: $KB_ID"
    set_config kb_id "$KB_ID"
    DATA_SOURCE_ID=""
    set_config data_source_id ""
  fi
fi

if [ -n "$KB_ID" ]; then
  echo "Knowledge base $KB_ID already exists, skipping creation"
else
  echo "Creating managed knowledge base: $KB_NAME"
  KB_ID=$(aws bedrock-agent create-knowledge-base \
    --name "$KB_NAME" \
    --role-arn "$ROLE_ARN" \
    --knowledge-base-configuration '{"type":"MANAGED","managedKnowledgeBaseConfiguration":{"embeddingModelType":"MANAGED"}}' \
    --region "$AWS_REGION" \
    --query knowledgeBase.knowledgeBaseId --output text)
  set_config kb_id "$KB_ID"
  # A new knowledge base means any stored data source ID is stale
  DATA_SOURCE_ID=""
  set_config data_source_id ""
fi

echo "Waiting for knowledge base $KB_ID to be ACTIVE..."
while true; do
  STATUS=$(aws bedrock-agent get-knowledge-base --knowledge-base-id "$KB_ID" \
    --region "$AWS_REGION" --query knowledgeBase.status --output text)
  [ "$STATUS" = "ACTIVE" ] && break
  if [ "$STATUS" = "FAILED" ]; then
    echo "Knowledge base creation failed" >&2
    exit 1
  fi
  sleep 5
done

# --- 5. Data source (the S3 bucket) ---
# Find the data source: the saved ID, or one with the same name left by an earlier run
if [ -z "$DATA_SOURCE_ID" ]; then
  DATA_SOURCE_ID=$(aws bedrock-agent list-data-sources --knowledge-base-id "$KB_ID" \
    --region "$AWS_REGION" \
    --query "dataSourceSummaries[?name=='$DATA_SOURCE_NAME'].dataSourceId | [0]" --output text)
  [ "$DATA_SOURCE_ID" = "None" ] && DATA_SOURCE_ID=""
fi

# Keep it only if it is healthy and points at the current bucket; otherwise recreate it
if [ -n "$DATA_SOURCE_ID" ]; then
  DS_JSON=$(aws bedrock-agent get-data-source --knowledge-base-id "$KB_ID" \
    --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" 2>/dev/null || echo "")
  DS_STATUS=$(echo "$DS_JSON" | jq -r '.dataSource.status // ""')
  DS_BUCKET=$(echo "$DS_JSON" | jq -r '.dataSource.dataSourceConfiguration.managedKnowledgeBaseConnectorConfiguration.connectorParameters | if type == "string" then fromjson else . end | .connectionConfiguration.bucketName // ""' 2>/dev/null || echo "")
  if [ "$DS_STATUS" = "AVAILABLE" ] && [ "$DS_BUCKET" = "$BUCKET_NAME" ]; then
    echo "Data source $DATA_SOURCE_ID already exists, skipping creation"
  else
    if [ -n "$DS_JSON" ]; then
      echo "Deleting data source $DATA_SOURCE_ID (status: ${DS_STATUS:-unknown}, bucket: ${DS_BUCKET:-unknown})"
      aws bedrock-agent delete-data-source --knowledge-base-id "$KB_ID" \
        --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" >/dev/null
      while aws bedrock-agent get-data-source --knowledge-base-id "$KB_ID" \
          --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" >/dev/null 2>&1; do
        sleep 5
      done
    fi
    DATA_SOURCE_ID=""
    set_config data_source_id ""
  fi
fi

if [ -z "$DATA_SOURCE_ID" ]; then
  echo "Creating data source: $DATA_SOURCE_NAME"
  DATA_SOURCE_CONFIG=$(jq -cn --arg bucket "$BUCKET_NAME" --arg account "$ACCOUNT_ID" '{
    type: "MANAGED_KNOWLEDGE_BASE_CONNECTOR",
    managedKnowledgeBaseConnectorConfiguration: {
      connectorParameters: {
        type: "S3",
        version: "1",
        connectionConfiguration: {bucketName: $bucket, bucketOwnerAccountId: $account}
      }
    }
  }')
  DATA_SOURCE_ID=$(aws bedrock-agent create-data-source \
    --knowledge-base-id "$KB_ID" \
    --name "$DATA_SOURCE_NAME" \
    --data-source-configuration "$DATA_SOURCE_CONFIG" \
    --region "$AWS_REGION" \
    --query dataSource.dataSourceId --output text)
  set_config data_source_id "$DATA_SOURCE_ID"
fi

# Managed data sources are created asynchronously: wait until AVAILABLE
echo "Waiting for data source $DATA_SOURCE_ID to be AVAILABLE..."
while true; do
  STATUS=$(aws bedrock-agent get-data-source --knowledge-base-id "$KB_ID" \
    --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" \
    --query dataSource.status --output text)
  [ "$STATUS" = "AVAILABLE" ] && break
  if [ "$STATUS" = "FAILED" ]; then
    echo "Data source creation failed:" >&2
    aws bedrock-agent get-data-source --knowledge-base-id "$KB_ID" \
      --data-source-id "$DATA_SOURCE_ID" --region "$AWS_REGION" \
      --query dataSource.failureReasons >&2
    exit 1
  fi
  sleep 5
done

# --- 6. Ingestion job ---
echo "Starting ingestion job..."
JOB_ID=$(aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DATA_SOURCE_ID" \
  --region "$AWS_REGION" \
  --query ingestionJob.ingestionJobId --output text)

while true; do
  STATUS=$(aws bedrock-agent get-ingestion-job \
    --knowledge-base-id "$KB_ID" \
    --data-source-id "$DATA_SOURCE_ID" \
    --ingestion-job-id "$JOB_ID" \
    --region "$AWS_REGION" \
    --query ingestionJob.status --output text)
  echo "Ingestion job status: $STATUS"
  [ "$STATUS" = "COMPLETE" ] && break
  if [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "STOPPED" ]; then
    echo "Ingestion job did not complete" >&2
    exit 1
  fi
  sleep 10
done

echo "Knowledge base ID: $KB_ID (saved to config.json as rag_v0.kb_id)"
echo "✓ RAG v0 knowledge base created successfully"

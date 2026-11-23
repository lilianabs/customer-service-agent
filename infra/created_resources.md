# Created Resources

## Orders Service

- **S3 Bucket**: `orders-service-db` — stores orders data and inventory
  - Uploaded file: `orders.json` (from `data/orders/orders.json`)

See [README.md](../README.md#infrastructure) for instructions on creating and destroying infrastructure.

## Orders API (Terraform module `infra/modules/orders`)

- **Lambda**: `orders-api` (Python 3.13, Powertools public layer) — reads `orders.json` from `orders-service-db`
- **IAM role**: `orders-lambda-exec` (basic execution + `s3:GetObject` on the orders data object)
- **API Gateway HTTP API**: `orders-api`, stage `v1`
  - `GET /orders/{order_number}`, `GET /orders/{order_number}/return-policy`, `GET /orders/{order_number}/refund-status`, `GET /orders/{order_number}/refund-amount`, `POST /orders/{order_number}/refund`, `GET /inventory/{product_code}`
- **CloudWatch log groups**: `/aws/lambda/orders-api`, `/aws/api_gw/orders-api`

## RAG v0 (managed Bedrock Knowledge Base, `infra/modules/rag_v0`)

Created by `infra/modules/rag_v0/create_kb_infra.sh` (called from `scripts/create_infra.sh`) and removed by `destroy_kb_infra.sh`. Names and IDs are saved in the `rag_v0` section of `config.json`.

- **S3 Bucket**: `product-information-kb-data-<random suffix>` (public access blocked) — stores the Markdown files from `data/knowledge-base/` under `knowledge_base/`
- **IAM role**: `rag-v0-kb-role` (trusted by `bedrock.amazonaws.com`, read access to the bucket above)
- **Bedrock Knowledge Base**: `rag-v0` — managed, out-of-the-box settings (Bedrock manages the vector store and embeddings); ID saved as `rag_v0.kb_id`
- **Data source**: `product-information` — the S3 bucket above; ID saved as `rag_v0.data_source_id`

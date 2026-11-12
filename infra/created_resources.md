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

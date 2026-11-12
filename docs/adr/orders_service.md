# ADR: Orders service architecture

- **Status:** Accepted
- **Date:** 2026-11-12
- **Related:** [Architecture](../architecture.md), [Implementation plan](../implementation_plan.md) (Day 1)

## Context

The refunds agent needs order details and return-policy checks, and the product questions agent needs inventory. Both reach this data through a thin `orders_client`, so the service behind it only has to be a small, cheap, easy-to-tear-down HTTP API over mock data.

This is a demo, and the data is mock data. A real order system (database, writes, auth) is out of scope. The refunds agent also does not issue refunds. It hands a case summary to a human for approval (see the architecture doc).

## Decision

### Overview

```
orders_client -> API Gateway (HTTP API, stage v1) -> Lambda (Python 3.13) -> S3 (orders.json, read-only)
```

- A single Lambda function (`orders-api`) behind an API Gateway HTTP API serves all endpoints.
- Order and inventory data is one static file, `orders.json`, in the S3 bucket `orders-service-db`.
- The Lambda has read-only access to that file. It cannot modify the data.

### The data is static

`orders.json` (source: `data/orders/orders.json`) is uploaded to S3 by `scripts/create_infra.sh`. The Lambda's IAM role has only `s3:GetObject` on that one object, with no `PutObject` and no access to other keys. So:

- The Lambda cannot write to the S3 bucket. The bucket contents change only when someone re-uploads the file (`create_infra.sh`).
- The data is loaded once per Lambda execution environment, at import time (`orders._load()`), and held in memory. Changes to the file in S3 are picked up only after a cold start, such as a redeploy.
- Purchase dates are stored as `purchased_days_ago` and resolved to real dates when the data is loaded, so the 30-day return window stays valid whenever the demo runs.

### `apply_refund` does not persist

`apply_refund` sets `refund_status = "refunded"` on the in-memory copy only. Consequences:

- The change is lost on a cold start.
- It is not shared between concurrent Lambda instances. One instance can report an order as refunded while another still reports it as not refunded.
- It is idempotent within an instance. Refunding an already-refunded order is a no-op that returns success.

This is acceptable because refunds are approved by a human outside this service, and the endpoint exists so the agent flow can be exercised end to end. If persistent refunds are needed later, the options are a DynamoDB table or write access to an S3 object, plus a conflict strategy. Neither is in scope now.

### API

REST-style routes, with the Lambda handler built on Powertools for AWS Lambda (`APIGatewayHttpResolver`, HTTP API payload format 2.0). Each route calls the function of the same name in `services/orders/orders.py`.

| Route | Function | Not found |
| --- | --- | --- |
| `GET /orders/{order_number}` | `get_order` | 404 |
| `GET /orders/{order_number}/return-policy` | `return_policy` | 200, `eligible: false`, reason "Order not found." |
| `GET /orders/{order_number}/refund-status` | `refund_status` | 404 |
| `GET /orders/{order_number}/refund-amount` | `refund_amount` | 404 |
| `POST /orders/{order_number}/refund` | `apply_refund` | 404 |
| `GET /inventory/{product_code}` | `get_product_inventory` | 404 |

`return_policy` keeps the behaviour of the underlying function for unknown orders, so the agent gets a policy answer instead of an error. The other routes return 404 through Powertools' `NotFoundError`.

### Code layout

- `services/orders/orders.py`: the data-access layer. It reads from S3 when `ORDERS_BUCKET` is set (the deployed Lambda) and from a local file otherwise (local development).
- `services/orders/lambda_function.py`: routing only, with no business logic.
- The Lambda zip contains `services/orders/`, excluding `mock_data/`. The local mock file is not bundled because the deployed function reads S3.
- `aws_lambda_powertools` is not bundled. The function uses the AWS public Powertools v3 layer for Python 3.13 on x86_64, pinned in `powertools_layer_arn`. `boto3` comes from the Lambda runtime.

### Infrastructure

Terraform module `infra/modules/orders`:

- Lambda `orders-api`, with a 30 second timeout, plus its log group.
- IAM role `orders-lambda-exec`: basic execution, and `s3:GetObject` on the orders data object.
- HTTP API `orders-api`, stage `v1` with auto-deploy and access logs. One route per endpoint, all pointing at a single Lambda proxy integration.
- Variables `orders_bucket_name`, `orders_data_key` and `powertools_layer_arn`. The defaults match `config.json`.

The data bucket is not managed by Terraform. `scripts/create_infra.sh` creates it, uploads the data and then applies the module. `scripts/destroy_infra.sh` destroys the module first and then deletes the bucket. `scripts/smoke_test_orders.sh` checks the deployed endpoints and runs at the end of `create_infra.sh`.

## Alternatives considered

- **Bundle `orders.json` in the Lambda zip.** This is simpler and needs no S3 permissions, but it ignores the bucket and makes updating data a redeploy. Rejected in favour of the architecture doc's "static files in S3" design.
- **Bundle `aws_lambda_powertools` with the code.** This is self-contained but needs a build step. The public layer keeps the zip tiny and needs no packaging.
- **A flat route per function name** (for example `GET /return_policy?order_number=...`). Rejected for REST-style routes keyed by order and product.
- **DynamoDB, or S3 write access, for refunds.** Rejected for now (see above).

## Consequences

- **Good:** very low cost and nothing to operate. The service is stateless, deploys and tears down with one script, and has a minimal permission surface (read one object).
- **Good:** local development works without AWS, since the data layer falls back to the local file.
- **Limitation:** refunds are not durable and can differ between Lambda instances. Agent demos and evaluations must not depend on a refund applied in one call showing up in a later call on a different instance.
- **Limitation:** there is no authentication. The API is public to anyone with the URL, which is acceptable only because the data is mock and the deployment is short-lived.
- **Limitation:** the Powertools layer version is pinned and must be bumped by hand. The module's state is local until the Terraform root with remote state is added.

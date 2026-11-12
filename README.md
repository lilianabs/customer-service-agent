# customer-service-agent

## Infrastructure

### Create Infrastructure

From the project root, run:

```bash
./scripts/create_infra.sh
```

This creates the S3 bucket for orders data and uploads the orders data file. Configuration is managed in `scripts/config.sh` — update `ORDERS_BUCKET_NAME`, `AWS_REGION`, or `ORDERS_DATA_PATH` as needed.

### Destroy Infrastructure

To remove all created resources:

```bash
./scripts/destroy_infra.sh
```

This removes the S3 bucket and all its contents (requires confirmation).

See [infra/created_resources.md](infra/created_resources.md) for a list of resources.

## Frontend

To run the static site: 

```bash
cd frontend
uv run python -m http.server 5500
```

In a web browser, go to `http://localhost:5500/`.

**Note:** This project is using the starter code from [AnyCompany Hair Care: build a LangGraph agent on Amazon Bedrock](https://github.com/sdahal1/anycompany-hair-care-langgraph-tutorial/tree/main).
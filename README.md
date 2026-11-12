# customer-service-agent

## Configuration

Global configuration is stored in `config.json` and can be accessed by shell scripts and Python modules.

**File locations:**
- `config.json` — project configuration (committed to git)
- `.env.example` — template for environment variables
- `.env` / `.env.local` — local environment variables (excluded from git, for secrets)

To use custom configuration:
1. Copy `.env.example` to `.env` and update as needed
2. Edit `config.json` for project-level settings

**Using config in Python:**
```python
from config import get_aws_region, get_orders_bucket, get

region = get_aws_region()  # From .env or config.json
bucket = get_orders_bucket()
custom_value = get("path.to.config.key")
```

**Using config in shell scripts:**
Configuration is read from `config.json` using `jq`.

## Infrastructure

### Create Infrastructure

From the project root, run:

```bash
./scripts/create_infra.sh
```

This creates the S3 bucket for orders data, uploads the orders data file, deploys the orders module (Lambda + API Gateway) with Terraform, and runs the smoke tests (`scripts/smoke_test_orders.sh`, which can also be run on its own against any base URL). Configuration is read from `config.json`.

### Destroy Infrastructure

To remove all created resources:

```bash
./scripts/destroy_infra.sh
```

This destroys the orders module and removes the S3 bucket and all its contents (requires confirmation).

See [infra/created_resources.md](infra/created_resources.md) for a list of resources.

## Frontend

To run the static site: 

```bash
cd frontend
uv run python -m http.server 5500
```

In a web browser, go to `http://localhost:5500/`.

**Note:** This project is using the starter code from [AnyCompany Hair Care: build a LangGraph agent on Amazon Bedrock](https://github.com/sdahal1/anycompany-hair-care-langgraph-tutorial/tree/main).
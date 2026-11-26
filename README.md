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

This creates the S3 bucket for orders data, uploads the orders data file, deploys the orders module (Lambda + API Gateway) with Terraform, and runs the smoke tests (`scripts/smoke_test_orders.sh`, which can also be run on its own against any base URL). It then creates the RAG v0 managed Bedrock knowledge base (`infra/modules/rag_v0/create_kb_infra.sh`, which needs a recent AWS CLI v2), saves its ID to `config.json` as `rag_v0.kb_id`, and runs the knowledge base smoke test (`scripts/smoke_test_kb_v0.py`). Configuration is read from `config.json`.

### Destroy Infrastructure

To remove all created resources:

```bash
./scripts/destroy_infra.sh
```

This destroys the RAG v0 knowledge base (with its IAM role and S3 bucket) and the orders module, and removes the orders S3 bucket and all its contents (requires confirmation).

### RAG v0 knowledge base

The RAG v0 knowledge base is a managed Amazon Bedrock Knowledge Base built with AWS CLI scripts, not Terraform. The scripts in `infra/modules/rag_v0/` are the source of truth for it. They run as part of `create_infra.sh` and `destroy_infra.sh`, and you can also run each step on its own from the project root:

```bash
# 1. Create the S3 bucket, upload data/knowledge-base/*.md, create the role, KB and data source, and run ingestion
./infra/modules/rag_v0/create_kb_infra.sh

# 2. Smoke test: KB status, ingestion status, and the 18-question retrieval eval (exit 0 = pass)
uv run python scripts/smoke_test_kb_v0.py

# 3. Destroy the KB, its IAM role and its S3 bucket (asks for confirmation)
./infra/modules/rag_v0/destroy_kb_infra.sh
```

The create script saves the bucket name, KB ID and data source ID to the `rag_v0` section of `config.json`. Re-running it reuses those values. The destroy script clears them. The create script needs AWS CLI v2 with the `bedrock-agent` commands.

See [infra/created_resources.md](infra/created_resources.md) for a list of resources.

## Tests

Tests live in `tests/` and run with pytest. The settings for pytest are in `pyproject.toml`. The agents code needs its workspace packages, so sync them first:

```bash
uv sync --all-packages

uv run pytest                    # all tests; live tests call Bedrock and need AWS credentials
uv run pytest -m "not live"      # routing logic only, no AWS calls
```

Tests that call an AWS service are marked `@pytest.mark.live`. The agents read their settings from `services/agents/config.json`, which holds the router model and the graph limits.

Type check and lint the agents code:

```bash
uv run pyright --pythonpath "$(uv run which python)" services/agents
uv run ruff check services/agents tests
```

## Frontend

To run the static site: 

```bash
cd frontend
uv run python -m http.server 5500
```

In a web browser, go to `http://localhost:5500/`.

**Note:** This project is using the starter code from [AnyCompany Hair Care: build a LangGraph agent on Amazon Bedrock](https://github.com/sdahal1/anycompany-hair-care-langgraph-tutorial/tree/main).

## Notebooks

The notebooks in `notebooks/` explore design choices before they go into the services. They are not part of the deployed system.

| Notebook | Purpose |
| --- | --- |
| `01_rag_v1_exploration.ipynb` | Explore the knowledge base, compare chunking strategies, and compare keyword, semantic and hybrid retrieval, then replay the chosen setup in OpenSearch |

**Setup**

1. Install the notebook dependencies (a separate `notebook` group in `pyproject.toml`):

   ```bash
   uv sync --group notebook
   ```

2. Start Jupyter Lab from the project root:

   ```bash
   uv run --group notebook jupyter lab notebooks/
   ```

   In VS Code, instead open the notebook and select the `.venv` interpreter as the kernel.

**Requirements by section**

- **Dataset, chunking and in-memory retrieval:** nothing extra. These sections run offline.
- **Semantic and hybrid retrieval:** AWS credentials with access to Amazon Bedrock (Titan Text Embeddings V2) in the region set in `config.json`. Embeddings are cached in `notebooks/.cache/`, which is git-ignored.
- **OpenSearch:** a running OpenSearch instance. For local development, start one with Docker. The notebook has the exact command in its OpenSearch section. To use an AWS domain instead, set `OPENSEARCH_TARGET=aws` and `OPENSEARCH_HOST=<domain endpoint>` before starting Jupyter. Destroy the domain when you're done measuring, because it has a running cost.

Run the cells in order from top to bottom. Some cells depend on values set earlier, such as `STRATEGY` and `ALPHA`.
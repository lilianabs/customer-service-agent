# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Customer Service Agent**: A hair care product customer service chatbot built with LangGraph that runs on AWS. The system detects user intent, answers product questions via RAG, and handles refund requests with escalation to humans.

Key documents:
- [Architecture](docs/architecture.md) — system design, components, tech stack
- [Implementation Plan](docs/implementation_plan.md) — 7-day development timeline

## Development Setup

**Python version**: 3.13 (pinned in `.python-version`)

**Package management**: Uses `uv` instead of pip. Install dependencies and run commands via `uv`:

```bash
# Install all dependencies
uv sync

# Run a script or module
uv run python <script.py>

# Run the local frontend web server
cd frontend && uv run python -m http.server 5500
# Then open http://localhost:5500/ in a browser
```

## High-Level Architecture

The system has four main components:

### 1. **Agents** (`services/agents/`)
Three LangGraph agents deployed on AWS Bedrock AgentCore:
- **Intent Router**: Classifies user intent and hands off to the right agent
- **Product Questions**: Answers product questions using the RAG service, queries inventory via Orders service
- **Refunds**: Checks order eligibility against 30-day return policy, escalates to human if approved

All agents go through thin client wrappers (`rag_client`, `orders_client`) so logic is testable and RAG variants are swappable.

### 2. **RAG Service** (`services/rag/`)
Exposes one retrieval interface with two interchangeable backends, selected by `RAG_VARIANT` environment variable:

| Variant | Backend | Details |
|---------|---------|---------|
| `v1` | OpenSearch | Full control over chunking, embedding, ranking; higher operational cost |
| `v2` | Bedrock Knowledge Bases | Managed ingestion; limited control over retrieval |

Both variants implement the same `Retriever` interface and read source documents from `data/knowledge_base/`. The variant is selected at deployment time (Terraform sets it) and can be overridden per evaluation run.

### 3. **Orders Service** (`services/orders/`)
AWS Lambda + API Gateway serving order status and inventory from S3 static files. Provides endpoints:
- `get_order` — fetch order details by ID
- `return_policy` — check 30-day refund eligibility
- `refund_status`, `refund_amount`, `apply_refund` — manage returns

The mock data store in `services/orders/store.py` loads from JSON and resolves relative dates (`purchased_days_ago`) to keep the demo evergreen. Dates are always relative to today, so the 30-day window stays valid.

### 4. **Frontend** (`frontend/`)
Static HTML/CSS/JavaScript chat UI, runs locally. Not deployed. Connects to the agents via HTTP, reads agent endpoints from Terraform outputs.

## Infrastructure (Terraform)

Root in `infra/`, organized by module:

| Module | Provisions | Deployed on |
|--------|-----------|-------------|
| `orders` | Lambda, API Gateway, S3 bucket, IAM | AWS |
| `rag` (v1, v2) | OpenSearch or Bedrock Knowledge Base, S3, IAM | AWS |
| `agents` | Bedrock AgentCore runtime, IAM | AWS |

- Remote state stored in S3
- `RAG_VARIANT` environment variable set by Terraform for the deployed RAG service
- Cost control: OpenSearch has a fixed running cost; destroy it when not measuring

Common patterns:
```bash
cd infra
terraform init
terraform plan -var-file="environments.tfvars"
terraform apply
terraform output  # Reads endpoints for frontend and eval scripts
terraform destroy # Removes all resources; use scripts/destroy_all to wrap
```

## Key Development Patterns

### Testing RAG retrieval
The RAG service has an interface contract. To test a variant:
```python
from services.rag.core import Retriever
# RAG_VARIANT env var selects v1 or v2 implementation
retriever = Retriever()
results = retriever.retrieve("question here")
# results is a list of (passage, source) tuples
```

### Testing agents locally
Agents are LangGraph graphs that invoke tool functions. To test:
```python
from services.agents.intent_router import graph as router_graph
from services.agents.product_qa import graph as qa_graph

state = {"messages": [{"role": "user", "content": "..."}]}
output = router_graph.invoke(state)
```

Mock the `orders_client` and `rag_client` for isolated tests.

### Guardrails
Cost limits are enforced:
- Max request length (characters)
- Max tokens per LLM call
- `recursion_limit` on agent graphs to prevent loops

Values are set per agent in `services/agents/` and enforced at invocation time.

## Data and Evaluation

### Knowledge Base
Source documents in `data/knowledge_base/`:
- Product specs, FAQs, usage guides
- Ingested by both RAG variants
- Updated as needed; ingest pipeline re-indexes automatically

### Golden Evaluation Set
Not yet written; due on Day 3 of the implementation plan. Will live in `data/eval/` with questions, expected answers, and expected source documents.

### Evaluation Results
- RAG evaluation results (retrieval quality, answer quality, latency, cost): `evals/results/rag/`
- System evaluation results (cost per conversation, p50/p95 latency): `evals/results/system/`

## Development Workflow

1. **Update knowledge base** → re-ingest by both RAG variants and run RAGAS regression test
2. **Update agent logic** → test locally against mocked services, then deploy via Terraform
3. **Compare RAG variants** → run evals on the golden set, results saved under `evals/results/`
4. **Measure system** → run end-to-end conversations through both RAG variants, compute metrics

## Observability

- **Agent traces**: AgentCore sends to CloudWatch; enable Transaction Search to view them
- **RAG latency**: Structured logs tagged with variant; custom CloudWatch metrics
- **Orders service**: Lambda and API Gateway logs

## Important Notes

- **This project is in early stages**: Day 1 is mostly done (orders service scaffold, repo setup). Agents, RAG variants, and evaluations are not yet built.
- **Development is time-boxed**: 7-day plan in [implementation_plan.md](docs/implementation_plan.md) with clear exit checks and a cut line for scope if days slip.
- **One environment only**: No dev/prod split.
- **Model routing and the monitoring dashboard are out of scope** for this phase (see Roadmap in architecture.md).
- **AWS access required**: Bedrock quota, S3, Lambda, API Gateway, OpenSearch (optional for v1 measurements).

## References

- Starter code adapted from [AWS LangGraph tutorial](https://builder.aws.com/content/3HS7p4Dme6C7ZXTZTq0Edy2NzPB/what-is-langgraph-a-beginners-guide-to-ai-agents-on-amazon-bedrock)
- RAGAS for evaluation: https://github.com/explodinggradients/ragas

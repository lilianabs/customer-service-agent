# Customer Service Agent: Implementation Plan

Nov 11, 2026 · @Liliana Badillo

## Scope and assumptions

The plan builds the system from the architecture doc in 7 days, working 5 to 8 hours a day.

- **Must have by day 7:** the full system (orders service, both RAG variants, three agents) and the results of both evaluations (RAG comparison and system-wide).
- **Already available:** orders starter code, local web chat UI, source documents, and an AWS account with Terraform and Bedrock access ready.
- **Not yet available:** the golden question set, written on day 3.
- **Out of scope:** model routing, the monitoring dashboard and security guardrails (Roadmap in the architecture doc).
- **Done means:** both evaluations have run, results are saved under `evals/results/`, and the RAG variant decision is written down.

## Timeline at a glance

Services first, then the RAG comparison, then the agents, and the system evaluation last.

| Day | Focus | Outcome |
| --- | --- | --- |
| 1 | Repo, Terraform, orders service | Orders endpoints live on AWS |
| 2 | RAG variant v1 (OpenSearch) | Retriever returns passages from the source documents |
| 3 | RAG variant v2 (Bedrock) and golden set | Both variants behind one interface, golden set written |
| 4 | RAG experiment | Results table and variant decision |
| 5 | Agents and guardrails | Three agents working locally |
| 6 | Agents on AgentCore, UI, observability | End-to-end conversation through the web chat UI |
| 7 | System evaluation and wrap-up | System metrics, regression test, docs updated |

## Daily plan

Each day ends with an exit check; do not start the next day until it passes, or cut scope using the list below.

### Day 1: Repo, Terraform, orders service

- [ ] Create the repo skeleton from the architecture doc and the Python 3.13 environment.
- [ ] Add the frontend starter code.
- [ ] Add the knowledge base data.
- [ ] Set up the Terraform root in `infra/` with the S3 remote state.
- [ ] Adapt the orders starter code, load static order and inventory data into S3, and deploy the `orders` module.
- [ ] Write `scripts/destroy_all` (wrapping `terraform destroy`) and test it on the orders module; extend it as each module is added.
- [ ] Write `orders_client` with a smoke test.

**Exit check:** all five endpoints (`return_policy`, `get_order`, `refund_status`, `refund_amount`, `apply_refund`) respond through API Gateway.

### Day 2: RAG variant v1 (OpenSearch)

- [ ] Define the `Retriever` interface and the `RAG_VARIANT` selection.
- [ ] Build the ingestion pipeline: load, chunk, embed and index the source documents.
- [ ] Deploy the `rag` module for v1.

**Exit check:** a test question returns relevant passages with their sources from OpenSearch.

### Day 3: RAG variant v2 (Bedrock) and golden set

- [ ] Deploy the `rag` module for v2 and sync the Knowledge Base from S3.
- [ ] Make v2 implement the same `Retriever` interface.
- [ ] Write the golden set under `data/eval/`: questions with expected answers and expected source documents.
- [ ] Write down how the variants differ (chunking, ranking) before measuring.

**Exit check:** the same question works against both variants by changing only `RAG_VARIANT`.

### Day 4: RAG experiment

- [ ] Agree the decision rule (quality, then cost, then latency) before running.
- [ ] Build the experiment runner under `evals/rag/` with RAGAS and the LLM-as-judge evals.
- [ ] Run both variants on the golden set, several runs per question, and save results under `evals/results/`.
- [ ] Produce the results table and write the variant decision under `docs/`.
- [ ] Add RAGAS to the CI/CD regression test.

**Exit check:** one results table covers retrieval quality, answer quality, latency and cost for both variants, and the decision is recorded.

### Day 5: Agents and guardrails

- [ ] Build the LangGraph graph for the intent router, product questions and refunds agents.
- [ ] Write `rag_client` and the tool wiring for both services, and the escalation summary for a human.
- [ ] Add the guardrails: max request length, max tokens and `recursion_limit`.
- [ ] Add a first version of short-term memory and choose a model per agent.

**Exit check:** scripted conversations for product questions, inventory questions and refunds work locally against the deployed services.

### Day 6: AgentCore, UI and observability

- [ ] Deploy the `agents` module on AgentCore.
- [ ] Connect the local web chat UI to the deployed agents using `terraform output`.
- [ ] Enable CloudWatch Transaction Search and OpenTelemetry tracing.
- [ ] Add a first version of long-term memory if time allows.

**Exit check:** a full conversation works through the UI, and its trace shows in CloudWatch.

### Day 7: System evaluation and wrap-up

- [ ] Write the scripted scenarios under `evals/system/`.
- [ ] Run them and compute cost per conversation and p50 and p95 latency.
- [ ] Decide the other system metrics and add them if time allows.
- [ ] Update the architecture doc with decisions and results, and confirm \`scripts/destroy\_all\` removes every module (orders, both RAG variants, agents) and the remote state resources are the only thing left.

**Exit check:** system results are saved, the architecture doc is up to date, and both evaluations are reproducible from the repo.

## Component briefs

Each component gets a one-page brief with its implementation details, written in the first 30 minutes of the day it is built, so the design is fixed before coding.

| Brief | Written on | Covers |
| --- | --- | --- |
| Infrastructure | Day 1 | Terraform layout, state, naming, IAM, destroy script |
| Orders service | Day 1 | Endpoints, data files in S3, request and response shapes |
| RAG service | Day 2 | `Retriever` interface, ingestion, both variants and how they differ |
| Evaluations | Day 3 | Golden set format, metrics, runner, results layout |
| Agents | Day 5 | Graphs, tools, handoffs, escalation, memory, guardrails |

## Risks and cut line

If a day slips by more than 2 hours, cut from the top of this list first.

| Priority to cut | What to drop | Effect |
| --- | --- | --- |
| 1 | Long-term memory (day 6) | Short-term memory only; long-term stays a roadmap item |
| 2 | Other system metrics (day 7) | Only cost per conversation, p50 and p95 latency |
| 3 | Different model per agent (day 5) | One model for all agents |
| 4 | RAGAS in CI/CD (day 4) | RAGAS runs manually until later |

| Risk | Mitigation |
| --- | --- |
| Golden set takes longer than the 3 to 4 hours on day 3 | Start with about 20 questions and grow it later |
| OpenSearch or Knowledge Base setup is slow to provision | Deploy the day 2 and day 3 modules early in the day and write code while they provision |
| Bedrock model access or quota limits | Check access on day 1 and request quota increases early |
| AgentCore deployment issues on day 6 | Test the agents locally on day 5 so only deployment is left to debug |
| OpenSearch running cost | Destroy it when not measuring |

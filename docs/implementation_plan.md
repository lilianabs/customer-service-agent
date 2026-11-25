# Customer Service Agent: Implementation Plan

Nov 11, 2026 · Last updated Nov 25, 2026 · @Liliana Badillo

## Scope and assumptions

The plan builds the system from the architecture doc in 7 days, working 5 to 8 hours a day. The comparisons between KB variants and product questions approaches follow after day 7, in the extra days listed under [Future steps](#future-steps).

- **Must have by day 7:** the full system on the v0 Knowledge Base baseline (orders service, product information KB v0, intent router, product questions and refunds agents) and the system-wide evaluation.
- **Already available:** orders starter code, local web chat UI, source documents, and an AWS account with Terraform and Bedrock access ready.
- **Not yet available:** the golden question set, written on day 6.
- **Out of scope:** model routing, the monitoring dashboard and security guardrails (Roadmap in the architecture doc).
- **Done means:** by day 7, the v0 baseline is measured and the system evaluation has run, with results saved under `evals/results/`. After the extra days, both comparisons have run and the KB variant decision and the product questions approach decision are written down.

## Timeline at a glance

Services first, then the Knowledge Base baseline, then the agents, then evals and docs, and the system test last. The KB and product approach comparisons come after.

| Day   | Focus                                  | Outcome                                                                                         |
| ----- | -------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1     | Repo, Terraform, orders service        | Orders endpoints live on AWS                                                                    |
| 2-3   | Knowledge Base v0 (managed)            | Managed KB baseline with retrieval metrics, KB deployed to AWS                                  |
| 4     | MCP server                             | MCP server for product information and orders                                                   |
| 5     | Agents, deployment and tracing         | Agents deployed on AgentCore with LangSmith and CloudWatch traces                               |
| 6     | Evals, guardrails and docs             | Ragas evals for product information and refunds, guardrails, architecture diagram and README updated |
| 7     | System test and UI                     | Full conversations through the web chat UI, system metrics, wrap-up                             |
| 8-10  | Extra: KB variants v1 and v2           | Three-way KB comparison and KB variant decision                                                 |
| 11-12 | Extra: product questions approaches    | Approach comparison across KB variants and approach decision                                    |

## Daily plan

Each day ends with an exit check; do not start the next day until it passes, or cut scope using the list below.

### Day 1: Repo, Terraform, orders service

- [✓] Create the repo skeleton from the architecture doc and the Python 3.13 environment.
- [✓] Add the frontend starter code.
- [✓] Add the knowledge base data.
- [✓] Add the orders service starter code.
- [✓] Add the orders service infra starter code.
- [✓] Add the Terraform starter code.
- [✓] Adapt the orders starter code.
- [✓] Load static order and inventory data into S3.
- [✓] Add global config for the project.
- [✓] Deploy the `orders` module.
- [✓] Write `scripts/destroy_all` (wrapping `terraform destroy`) and test it on the orders module; extend it as each module is added.
- [✓] Write `orders_client` with a smoke test.

**Exit check:** all six endpoints (`return_policy`, `get_order`, `refund_status`, `refund_amount`, `apply_refund`, `get_product_inventory`) respond through API Gateway.

### Day 2-3: Knowledge Base v0

- [✓] Experiment with the managed Amazon Bedrock Knowledge Base to get a baseline and retrieval metrics for v0.
- [✓] Deploy KB (v0) to AWS.

**Exit check:** `uv run python scripts/smoke_test_kb_v0.py` exits 0 (KB and ingestion status are ready, and the retrieval eval passes).

### Day 4: MCP Server

- [✓] Write ADR for MCP pserver.
- [✓] Create MCP server for Product Information component and orders service.

**Exit check:** the MCP server is deployed to AgentCore Runtime, `scripts/smoke_test_mcp.sh` passes, and its product information and orders tools return data.

### Day 5: Agents, deployment and tracing

- [ ] Build the LangGraph graph for the intent router, product questions and refunds agents.
- [ ] Write `rag_client` for the product information KB, `orders_client` for the refunds agent, the tool wiring for both, and the escalation summary for a human.
- [ ] Add a first version of short-term memory and choose a model per agent.
- [ ] Add a first version of long-term memory if time allows.
- [ ] Deploy the `agents` module on AgentCore.
- [ ] Add LangSmith tracing.
- [ ] Enable CloudWatch Transaction Search.

**Exit check:** the intent router hands a product question to the product questions component and a refund request to the refunds agent on the deployed agents, each gets a correct reply, and their traces show in LangSmith and CloudWatch.

### Day 6: Evals, guardrails and docs

- [ ] Create Evals data set for Product Information component using ragas.
- [ ] Create Evals data set for Refunds agent.
- [ ] Run evals using ragas for product information component and refunds agent.
- [ ] Add the guardrails: max request length, max tokens and `recursion_limit`.
- [ ] Update the architecture diagram in the architecture doc and the README.

**Exit check:** ragas results for product information and refunds are saved under `evals/results/`, the guardrails are in place, and the architecture diagram and README match the system.

### Day 7: System test and UI

- [ ] Connect the local web chat UI to the deployed agents using `terraform output`.
- [ ] Write the scripted scenarios under `evals/system/`.
- [ ] Run them and compute cost per conversation and p50 and p95 latency.
- [ ] Test full conversations through the web chat UI and fix what breaks.
- [ ] Decide the other system metrics and add them if time allows.
- [ ] Update the architecture doc with decisions and results, and confirm `scripts/destroy_all` removes every module deployed so far (orders, the v0 KB, agents) and the remote state resources are the only thing left.

**Exit check:** a full conversation works through the local web chat UI, system results are saved, the architecture doc is up to date, and the system evaluation is reproducible from the repo.

## Component briefs

Each component gets a one-page brief with its implementation details, written in the first 30 minutes of the day it is built, so the design is fixed before coding.

| Brief                          | Written on | Covers                                                                   |
| ------------------------------ | ---------- | ------------------------------------------------------------------------ |
| Infrastructure                 | Day 1      | Terraform layout, state, naming, IAM, destroy script                     |
| Orders service                 | Day 1      | Endpoints, data files in S3, request and response shapes                 |
| Product information KB         | Day 2      | `Retriever` interface, ingestion, the v0 setup (v1 and v2 briefs on days 8 and 9) |
| MCP server                     | Day 4      | Two tool groups (product information and orders), tool schemas, how the clients call them |
| Agents                         | Day 5      | Graphs, tools, handoffs, escalation, memory, input and output guardrails (PII, prompt injection, response validation), LangSmith and CloudWatch tracing |
| Evaluations                    | Day 6      | Golden set format, metrics, runner, results layout                       |
| Product questions approaches   | Day 7     | Simple RAG workflow and agentic RAG, tools, how they are compared        |

## Risks and cut line

If a day slips by more than 2 hours, cut from the top of this list first.

| Priority to cut | What to drop                                              | Effect                                                                 |
| --------------- | --------------------------------------------------------- | ---------------------------------------------------------------------- |
| 1               | Product questions v1, agentic RAG (day 11)                | Only the simple RAG workflow is built; no approach comparison (day 12) |
| 2               | KB variants v1 and v2 (days 8-9)                          | Only the v0 KB is built; no KB comparison (day 10), and the approach comparison (day 12) runs on v0 only |

| Risk                                                    | Mitigation                                                                              |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Golden set takes longer than the 3 to 4 hours on day 6  | Start with about 20 questions and grow it later                                         |
| OpenSearch or Knowledge Base setup is slow to provision | Deploy the KB modules early in the day and write code while they provision              |
| Bedrock model access or quota limits                    | Check access on day 1 and request quota increases early                                 |
| AgentCore deployment issues on day 5                    | Get the agents working locally first, so only deployment is left to debug               |
| OpenSearch running cost                                 | Destroy it when not measuring                                                           |

## Future steps

The v0 Knowledge Base is the baseline, built first so the agents can be tested as a whole. The extra days below complete the comparisons. Phase 1 compares the KB variants, and Phase 2 compares the product questions approaches against each KB variant. Each day is an estimate, to be scheduled after day 7.

### Phase 1: Knowledge Base variants (days 8-10)

Build v1 (OpenSearch) and v2 (S3 Vectors), then compare all three KB variants on the same golden set.

#### Day 8: KB variant v1 (OpenSearch)

- [✓] Add RAG variant v1 exploration notebook.
- [✓] Experiment design for variants v1 and v2.
- [ ] Define the `Retriever` interface and the `RAG_VARIANT` selection (`v0`, `v1`, `v2`).
- [ ] Build the ingestion pipeline: load, chunk, embed and index the source documents.
- [ ] Deploy the `rag` module for v1.

**Exit check:** a test question returns relevant passages with their sources from OpenSearch.

#### Day 9: KB variant v2 (S3 Vectors)

- [ ] Deploy the `rag` module for v2 and sync the Knowledge Base from S3.
- [ ] Make v2 implement the same `Retriever` interface.
- [ ] Write down how the variants differ (chunking, ranking) before measuring.

**Exit check:** the same question works against v0, v1 and v2 by changing only `RAG_VARIANT`.

#### Day 10: KB comparison

- [ ] Run the parity check between v1 and v2 before measuring.
- [ ] Agree the decision rule (quality, then cost, then latency) before running.
- [ ] Run v0, v1 and v2 on the golden set, several runs per question, and save results under `evals/results/`.
- [ ] Produce the KB results table and write the KB variant decision under `docs/`.
- [ ] Add RAGAS to the CI/CD regression test.

**Exit check:** one KB results table covers all three variants, and the KB variant decision is recorded.

### Phase 2: Product questions approaches (days 11-12)

Build the agentic RAG approach next to the simple RAG workflow, then compare both against each KB variant.

#### Day 11: Product questions approach v1 (agentic RAG)

- [ ] Write the agentic RAG brief before coding (the model decides whether and what to retrieve, and can retrieve again).
- [ ] Build the agentic RAG approach as a LangGraph graph, using only `rag_client`.
- [ ] Make both approaches selectable, so each can run against any KB variant.

**Exit check:** both approaches answer the scripted product questions against the same KB variant.

#### Day 12: Product questions comparison

- [ ] Agree the decision rule for the two approaches before running.
- [ ] Run both approaches against each KB variant (six combinations) on the golden set, several runs per question, and save results under `evals/results/`.
- [ ] Produce the results table and write the product questions approach decision under `docs/`.

**Exit check:** one results table covers all six combinations, and the product questions approach decision is recorded.

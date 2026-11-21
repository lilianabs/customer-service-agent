# ADR: Product information RAG system architecture

- **Status:** Accepted for v0 (the baseline knowledge base). The product questions approach is still open and will be chosen from experiments.
- **Date:** 2026-11-19 · **Updated:** 2026-11-20
- **Related:** [Architecture](../architecture.md), [Implementation plan](../implementation_plan.md) (Day 2-3), [v0 exploration notebook](../../notebooks/03_rag_v0_exploration.ipynb)

## Context

The product questions component answers product questions from the product information in `data/knowledge_base/` (product pages, FAQ and hair-type guide, 11 Markdown files). It does not use the orders service: inventory questions are out of scope for now, so the component reads only from the product information Knowledge Base (KB).

Two decisions are still open, and this ADR separates them:

1. **Product questions approach.** Two candidates: v0, a simple RAG workflow (a fixed retrieve-then-generate pipeline), and v1, an agentic RAG (the model decides whether and what to retrieve, and can retrieve again). The choice is made from experiments, not up front.
2. **KB variant.** Three ways to build the retrieval store: v0 (managed Amazon Bedrock Knowledge Base with default settings), v1 (Amazon OpenSearch Service with custom settings) and v2 (self-managed Bedrock Knowledge Base with custom settings and Amazon S3 Vectors).

The product questions approach and the KB variant are chosen separately. Either approach can run against any KB variant.

All KB variants implement the same `Retriever` interface, and the variant is selected by `KB_VARIANT` (`v0`, `v1` or `v2`).

## Decision

**Build v0 first, as a baseline.** The managed Knowledge Base with default settings is the first KB variant to build and measure. It lets us move quickly to testing the agent system as a whole. v1 and v2 are measured after it, so the comparison can be completed later.

### KB variant v0: managed Bedrock Knowledge Base (baseline)

| Component | Setting |
| --- | --- |
| Source | 11 Markdown files from `data/knowledge_base/`, uploaded to a private S3 bucket under `knowledge_base/` |
| Chunking | Knowledge Base default: text is split into chunks of about 300 tokens |
| Embeddings | Managed by the Knowledge Base (service default) |
| Vector store | Managed by the Knowledge Base setup |
| Retrieval | Semantic search through the Bedrock `retrieve` API |
| top-k | 5 for the baseline result. The notebook requests 10 results, so metrics can be read at any k |

### Baseline result

The first measurement is in `notebooks/03_rag_v0_exploration.ipynb`. It runs an 18-question eval set: 9 lexical questions (wording close to the source) and 9 paraphrased questions. Each question lists the document IDs that should come back.

| Metric (k=5) | Result |
| --- | --- |
| hit@1 | 1.000 |
| hit@k | 1.000 |
| recall@k | 1.000 |
| MRR | 1.000 |
| Approximate context tokens | about 1,917 |

**What this means:** the baseline is correct on every question, so this eval set cannot tell the KB variants apart. One question is worth 0.056 of a metric. A harder set, with more questions and more paraphrases, is needed before comparing v0, v1 and v2. The retrieval-only numbers say nothing yet about answer quality, latency or cost.

## Consequences

- The product questions component has no access to the orders service. The `get_product_inventory` endpoint remains in the orders service but has no caller for now.
- The product questions approach (v0 or v1) is chosen from experiments, using the same golden set and metrics for both. How the approaches are compared is still to be decided.
- The v1 vs v2 comparison (OpenSearch vs S3 Vectors) is still to be run, following [architecture.md](../architecture.md) (Experiment design). v0 is not part of that controlled experiment.
- The eval set needs to grow before its scores can separate the variants.
- The notebook uses an existing Knowledge Base (its ID is set in the notebook) and creates and deletes only its own S3 bucket. The v0 Knowledge Base is not yet deployed through Terraform (see the Day 2-3 items in the implementation plan).

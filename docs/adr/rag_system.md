# ADR: Product information RAG system architecture

- **Status:** Accepted
- **Date:** 2026-11-19
- **Related:** [Architecture](../architecture.md), [Implementation plan](../implementation_plan.md) (Day 2-3), [Orders service architecture](orders_service.md) 

## Context

The product questions agent needs product informatiomation and inventory. It reachers this data through a RAG system (through `Retriever` interface) as well as the orders service (through `orders_client`).

## Decision

The RAG product information system consists of 3 versions:

- **v0**: Uses Amazon Bedrock Knowledge Base (Managed KB) with settings out of the box.
- **v1**: Uses Opensearch with more advanced settings.
- **v2**: Uses Amazon Bedrock Knowledge Base with custom settings.

### v0

This is an Amazon Bedrock knowledge base with the following components:

- Chuncking strategy: Default chunking - text is spplited into chunks of approximately 300 tokens.
- Embeddings: Managed embedding.
- Retrieval: Semantic search.
- top-k: TBD
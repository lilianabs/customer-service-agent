# Technical Details: RAG Chunking and Retrieval Metrics

Notes from a discussion about the RAG v1/v2 comparison and the metrics in `notebooks/01_rag_v1_exploration.ipynb`. Written for later reference.

## 1. Chunking strategies

Chunking splits each source document into smaller pieces before embedding. At query time, retrieval returns the pieces that best match the question, not whole documents.

### Bedrock Knowledge Bases (v2) options

**Fixed-size**
- Splits every N tokens (Bedrock's default is about 300 tokens) with overlap (about 20%), so text at a boundary appears in two neighboring chunks.
- Simple and predictable. Can cut mid-sentence or separate a spec from its heading.

**Hierarchical**
- Creates two levels: small child chunks and larger parent chunks that contain them.
- Search runs over the child chunks for precise matching. The system returns the parent chunk so the LLM gets more surrounding context.
- Useful for documents with sections, such as usage guides where a step needs its heading and warnings.

**Semantic**
- Ignores length. Compares neighboring sentences using embeddings and starts a new chunk where the topic shifts.
- Chunks follow meaning but vary in size. Ingestion costs more.

**No chunking**
- Each source file becomes one chunk and one embedding.
- Works when each file is already a self-contained unit (for example, one FAQ entry per file).
- Breaks down for long documents: one embedding has to represent the whole file, so specific facts get diluted, and very long files can exceed the embedding model's input limit.

**Custom chunking via Lambda**
- A Lambda function receives each document and returns chunks, so any custom logic can be applied (for example, splitting on markdown headings).

### Implications for the v1 (OpenSearch) notebook

In v1 you choose the chunking strategy yourself. Record these for each run:
- Chunk unit (tokens or characters) and size
- Overlap
- Whether splits respect headings or sentences
- Whether parent/child relationships are used
- Whether each chunk keeps its source document as metadata (needed for the expected-source labels in the golden set)

For a fair v1 vs. v2 comparison, start v1 with the same fixed-size settings Bedrock uses by default. Then the comparison isolates the retrieval backend rather than the chunking. If v1 uses a different strategy (hierarchical or heading-aware), v2 can match it only through the custom Lambda option.

Verify the Bedrock default values (about 300 tokens, 20% overlap) against current AWS documentation before relying on them.

## 2. Retrieval metrics in the notebook

Labels are per document: a chunk counts as relevant if it comes from a relevant source document, even if it doesn't contain the exact answer. One relevant document can therefore supply several hits in the top results.

For each query, the notebook computes the following, then averages across queries.

**`hit@1`, `hit@3`**
- For one query, 1 if any of the top k chunks comes from a relevant document, otherwise 0.
- `hit@1` is strict: the top result must be relevant.
- `hit@3` is lenient: a relevant result appears in the top three. High `hit@3` with low `hit@1` means the right documents are found but ranked poorly.

**`mrr` (mean reciprocal rank), within top 10**
- For one query, 1 / rank of the first relevant chunk (1, 0.5, 0.33, ...). Scores 0 if no relevant chunk is in the top 10.
- Gives partial credit for rank position. Ignores relevant chunks after the first one.

**`ctx_tokens@3`**
- Approximate tokens in the top-3 chunks, averaged across queries.
- Not a quality metric. Estimates how much text the LLM must read, which drives cost and can add noise.
- Larger chunks raise this number even when hit rates stay the same.

### Worked example

| Query | Top 3 results (R = relevant) | hit@1 | hit@3 | Reciprocal rank |
|---|---|---|---|---|
| A | not R, R, not R | 0 | 1 | 0.5 |
| B | R, not R, not R | 1 | 1 | 1 |
| C | none relevant in top 10 | 0 | 0 | 0 |

- hit@1 ≈ 0.33, hit@3 ≈ 0.67, MRR = 0.5

## 3. Why recall is not in the notebook yet

- With one relevant document per query, `hit@k` and `recall@k` give the same result. Recall adds information only when a query has several relevant documents: it measures the fraction of them retrieved, while `hit@k` only checks for at least one.
- For RAG, recall matters because the LLM needs all the facts that answer a question. If an answer depends on two documents, `hit@3` can look good while half the answer is missing.

**Other candidate metrics**
- **precision@k**: shows how much of the context is noise. Less informative here because multiple chunks from one relevant document inflate it.
- **nDCG@k**: uses graded relevance (answers the question vs. related topic). Needs more labeling effort.
- **RAGAS**: named in `CLAUDE.md` as the evaluation tool. Its context recall and context precision work at the chunk level. Its faithfulness and answer relevancy metrics evaluate the LLM's answer, which the retrieval-only metrics don't measure. These are LLM-judged and cost more to run.

**Suggested next step**
- Add `recall@3` and `recall@10` if the golden set will include queries with multiple relevant documents.
- Keep `hit@1` and `mrr` for ranking quality.
- Add RAGAS or answer-level checks once the pipeline generates answers.
- The choice depends on how the golden set (`data/eval/`, due Day 3) labels multi-document questions. That set isn't written yet.

## 4. Retrieval modes

The notebook (`notebooks/01_rag_v1_exploration.ipynb`, Part 4) compares four modes. They differ in how each chunk is scored against the question. All four are run on the same eval set.

**Keyword (BM25)**
- Scores each chunk by how many of the question's words it contains, weighted by how rare each word is across the corpus. Stopwords are removed. No stemming, so "iron" and "irons" don't match.
- Strong when the question shares exact terms with the document ("Is niacinamide in any of your products?").
- Weak on paraphrases: "greasy" doesn't match "oily," and "money back" doesn't match "refund." Words like *vegan* and *hair* appear in almost every doc, so they don't separate products.
- OpenSearch equivalent: `multi_match` (BM25 is the default similarity).

**Semantic (k-NN over embeddings)**
- Embeds the question and each chunk with Titan Text Embeddings V2, then ranks chunks by cosine similarity. Meaning matters more than exact words, so paraphrases work.
- Weaker on exact identifiers, product names, and rare terms, because the embedding can blur them.
- OpenSearch equivalent: a `knn` query on a `knn_vector` field (HNSW, Lucene engine).

**Hybrid, weighted (`hybrid_weighted`)**
- Runs both scorers, rescales each score list to 0–1 with min-max normalization, then combines them: `alpha × semantic + (1 − alpha) × keyword`.
- `alpha` = 0 is keyword only; 1 is semantic only. Part 4d sweeps alpha in steps of 0.1.
- Sensitive to normalization, because min-max depends on the highest and lowest scores in each query's results.
- OpenSearch equivalent: a `hybrid` query with a `normalization-processor` using the same weights.

**Hybrid, reciprocal rank fusion (`hybrid_rrf`)**
- Ignores raw scores and uses only each chunk's rank in each list: `sum of 1 / (60 + rank)`.
- No weights to tune and no dependence on score scales. Usually a robust default, but it can't express "trust semantic more" beyond what the ranks show.
- OpenSearch equivalent: a `hybrid` query with a `score-ranker-processor` (RRF). Requires OpenSearch 2.19 or later.

**Reading the comparison**
- Compare on the `paraphrase` vs. `lexical` split (Part 4c, cell 29). Keyword should do well on lexical questions and poorly on paraphrases; semantic the reverse; hybrid should handle both.
- Use `ctx_tokens@3` as a tiebreaker.
- With 18 questions, one question moves MRR by about 0.056, so treat small differences as noise.

**Connection to Bedrock KB (v2)**
- Bedrock's Retrieve API offers `HYBRID` and `SEMANTIC` search types. You can't set hybrid weights or choose RRF versus min-max, so v1 gives more control over this choice.
- Not yet verified against current AWS documentation. Confirm before the Day 3 comparison.

## Open items
- Confirm Bedrock default chunk size and overlap values.
- Confirm Bedrock Retrieve search type options (`HYBRID`, `SEMANTIC`).
- Decide how multi-document questions are labeled in the golden set.
- Decide whether to add recall metrics to the notebook.

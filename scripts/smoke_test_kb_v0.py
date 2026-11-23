#!/usr/bin/env python3
"""Smoke test for the RAG v0 managed Bedrock knowledge base.

Run it after infra/modules/rag_v0/create_kb_infra.sh. It reuses the evaluation
from notebooks/03_rag_v0_exploration.ipynb: 18 questions (lexical and
paraphrased), each with its relevant document IDs, scored with hit@1, hit@k,
recall@k and MRR.

Usage:
    uv run python scripts/smoke_test_kb_v0.py [--kb-id ID] [--k 10] [--metrics-k 5]

The knowledge base ID and region are read from config.json (rag_v0.kb_id and
aws.region). Exit code: 0 all checks passed, 1 a check failed, 2 bad setup.
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

# Same questions as the notebook. One question is worth 1/18 = 0.056 of a metric.
EVAL_SET = [
    {"q": "Is the bond oil safe for bleached hair?", "relevant": ["repair-bond-oil"], "type": "lexical"},
    {"q": "How much does shipping cost?", "relevant": ["faq"], "type": "lexical"},
    {"q": "Up to what temperature does the heat protectant work?", "relevant": ["heat-shield-mist"], "type": "lexical"},
    {"q": "Is niacinamide in any of your products?", "relevant": ["scalp-reset-serum"], "type": "lexical"},
    {"q": "Does the conditioner contain silicones?", "relevant": ["silk-slip-conditioner"], "type": "lexical"},
    {"q": "Is there a holiday sale?", "relevant": ["aws-developers-discount"], "type": "lexical"},
    {"q": "Are your products tested on animals?", "relevant": ["faq"], "type": "lexical"},
    {"q": "How often should I use the deep conditioning mask?", "relevant": ["weekly-repair-mask"], "type": "lexical"},
    {"q": "What routine do you recommend for fine hair?", "relevant": ["hair-type-guide"], "type": "lexical"},
    {"q": "What should I spray on before using my flat iron?", "relevant": ["heat-shield-mist"], "type": "paraphrase"},
    {"q": "My scalp gets greasy really fast, what can help?", "relevant": ["scalp-reset-serum", "hair-type-guide"], "type": "paraphrase"},
    {"q": "Do you have any promo codes?", "relevant": ["aws-developers-discount"], "type": "paraphrase"},
    {"q": "Which product gives my curls hold without making them stiff?", "relevant": ["air-dry-styling-gel", "define-curl-cream"], "type": "paraphrase"},
    {"q": "Can I get my money back if I already opened the bottle?", "relevant": ["faq"], "type": "paraphrase"},
    {"q": "How many days do I have to send something back?", "relevant": ["faq"], "type": "paraphrase"},
    {"q": "Which shampoo won't wash out my dye job?", "relevant": ["hydra-wash-shampoo"], "type": "paraphrase"},
    {"q": "When will I see the money from my return on my card?", "relevant": ["faq"], "type": "paraphrase"},
    {"q": "Will the product with argan oil make thin hair look oily?", "relevant": ["repair-bond-oil"], "type": "paraphrase"},
]

# Minimum scores to pass. The notebook baseline is 1.0 everywhere; these leave
# room for one missed question (0.056) so a single borderline answer does not fail the run.
THRESHOLDS = {"hit@1": 0.9, "hit@k": 0.94, "recall@k": 0.9, "mrr": 0.9}


def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)


def approx_tokens(text: str) -> int:
    return round(len(text) / 4)


def retrieve(client, kb_id: str, query: str, k: int) -> list[dict]:
    """Search the knowledge base and return hits as {doc_id, text}."""
    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={"managedSearchConfiguration": {"numberOfResults": k}},
    )
    return [
        {
            # e.g. "repair-bond-oil", matches the ids in EVAL_SET
            "doc_id": Path(item["documentId"]).stem,
            "text": item["content"]["text"],
        }
        for item in response["retrievalResults"]
    ]


def run(client, kb_id: str, k: int) -> list[dict]:
    """Run every eval question once and keep the full ranking."""
    rows = []
    for item in EVAL_SET:
        hits = retrieve(client, kb_id, item["q"], k)
        rows.append({
            "q": item["q"],
            "type": item["type"],
            "relevant": set(item["relevant"]),
            "ranking": [h["doc_id"] for h in hits],
            "tokens": [approx_tokens(h["text"]) for h in hits],
        })
    return rows


def first_relevant_rank(row: dict) -> int | None:
    return next((i + 1 for i, d in enumerate(row["ranking"]) if d in row["relevant"]), None)


def metrics_at(rows: list[dict], k: int) -> dict:
    """hit@1, hit@k, recall@k, MRR (full ranking) and context tokens in the top k, averaged."""
    out = {"hit@1": 0.0, "hit@k": 0.0, "recall@k": 0.0, "mrr": 0.0, "ctx_tokens@k": 0.0}
    for r in rows:
        first = first_relevant_rank(r)
        out["hit@1"] += float(first == 1)
        out["hit@k"] += float(first is not None and first <= k)
        out["recall@k"] += len(r["relevant"] & set(r["ranking"][:k])) / len(r["relevant"])
        out["mrr"] += 1 / first if first else 0.0
        out["ctx_tokens@k"] += sum(r["tokens"][:k])
    return {name: round(total / len(rows), 3) for name, total in out.items()}


def check_knowledge_base(agent_client, kb_id: str) -> bool:
    """The KB must be ACTIVE and every data source's latest ingestion job COMPLETE."""
    ok = True
    kb = agent_client.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]
    status = kb["status"]
    print(f"{'PASS' if status == 'ACTIVE' else 'FAIL'}  knowledge base {kb['name']} status: {status}")
    ok &= status == "ACTIVE"

    sources = agent_client.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]
    if not sources:
        print("FAIL  knowledge base has no data source")
        return False
    for source in sources:
        jobs = agent_client.list_ingestion_jobs(
            knowledgeBaseId=kb_id,
            dataSourceId=source["dataSourceId"],
            sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
            maxResults=1,
        )["ingestionJobSummaries"]
        job_status = jobs[0]["status"] if jobs else "NO INGESTION JOB"
        passed = job_status == "COMPLETE"
        print(f"{'PASS' if passed else 'FAIL'}  data source {source['name']} last ingestion: {job_status}")
        ok &= passed
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--kb-id", help="knowledge base ID (default: rag_v0.kb_id from config.json)")
    parser.add_argument("--k", type=int, default=10, help="results to retrieve per question (default 10)")
    parser.add_argument("--metrics-k", type=int, default=5, help="k used for the metrics (default 5)")
    args = parser.parse_args()

    config = load_config()
    region = config["aws"]["region"]
    kb_id = args.kb_id or config.get("rag_v0", {}).get("kb_id", "")
    if not kb_id:
        print("No knowledge base ID. Run infra/modules/rag_v0/create_kb_infra.sh first or pass --kb-id.", file=sys.stderr)
        return 2
    if args.metrics_k > args.k:
        print("--metrics-k cannot be larger than --k", file=sys.stderr)
        return 2

    print(f"Smoke testing knowledge base {kb_id} in {region}\n")

    passed = failed = 0
    try:
        agent_client = boto3.client("bedrock-agent", region_name=region)
        runtime_client = boto3.client("bedrock-agent-runtime", region_name=region)

        # 1. Status of the knowledge base and its latest ingestion
        if check_knowledge_base(agent_client, kb_id):
            passed += 1
        else:
            failed += 1
        print()

        # 2. Retrieval over the eval set
        rows = run(runtime_client, kb_id, args.k)
    except (ClientError, BotoCoreError) as error:
        print(f"AWS error: {error}", file=sys.stderr)
        return 2

    for r in rows:
        first = first_relevant_rank(r)
        status = "PASS" if first is not None and first <= args.metrics_k else "FAIL"
        rank = f"rank {first}" if first else "not found"
        top = ", ".join(r["ranking"][:3]) or "no results"
        print(f"{status}  [{r['type']:<10}] {r['q']}\n      relevant: {sorted(r['relevant'])} -> {rank}; top 3: {top}")

    empty = [r["q"] for r in rows if not r["ranking"]]
    print()
    if empty:
        print(f"FAIL  {len(empty)} question(s) returned no results")
        failed += 1
    else:
        print("PASS  every question returned results")
        passed += 1

    # 3. Metrics against the thresholds
    print(f"\nMetrics at k={args.metrics_k} ({len(rows)} questions, one question = {1 / len(rows):.3f}):")
    for label, subset in (("all", rows),
                          ("lexical", [r for r in rows if r["type"] == "lexical"]),
                          ("paraphrase", [r for r in rows if r["type"] == "paraphrase"])):
        m = metrics_at(subset, args.metrics_k)
        print(f"  {label:<10} " + "  ".join(f"{name}={value}" for name, value in m.items()))

    overall = metrics_at(rows, args.metrics_k)
    print()
    for name, minimum in THRESHOLDS.items():
        ok = overall[name] >= minimum
        print(f"{'PASS' if ok else 'FAIL'}  {name} = {overall[name]} (minimum {minimum})")
        passed += ok
        failed += not ok

    print(f"\nSummary: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

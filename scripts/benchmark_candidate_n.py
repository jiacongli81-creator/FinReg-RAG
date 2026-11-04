"""Compare actual cross-encoder ranking time for three candidate sizes."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import get_chunks
from app.services.embeddings import cosine, embed
from app.services.keywords import rank_keywords
from app.services.reranker import _model, rerank_candidates
from scripts.evaluate_api import match_evidence

IDS = ("qa-02", "qa-28", "qa-41", "qa-52", "qa-61")
NS = (20, 30, 50)


def evidence_rank(evidence: str, ranked: list[tuple[float, object]]) -> int | None:
    return next((i for i, (_, row) in enumerate(ranked, 1) if match_evidence(evidence, row["content"])[0]), None)


def main() -> int:
    old = json.loads((ROOT / "data/test/finance_qa_40.json").read_text(encoding="utf-8"))
    new = json.loads((ROOT / "data/test/finance_qa_60.json").read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in old + new}
    rows = get_chunks(only_valid=True)
    _model()  # Exclude one-time model load from the timed calls.
    results = []
    for index, case_id in enumerate(IDS):
        case = by_id[case_id]
        question = case["question"]
        vector = embed(question)
        semantic = sorted(((cosine(vector, json.loads(row["embedding"])), row) for row in rows), key=lambda pair: (-pair[0], pair[1]["id"]))
        keyword = rank_keywords(question, rows, limit=max(NS))
        order = NS[index % len(NS):] + NS[:index % len(NS)]
        for n in order:
            fused = {}
            for ranked in (semantic[:n], keyword[:n]):
                for rank, (_, row) in enumerate(ranked, 1):
                    score = fused[row["id"]][0] if row["id"] in fused else 0.0
                    fused[row["id"]] = (score + 1 / (60 + rank), row)
            candidates = sorted(fused.values(), key=lambda pair: (-pair[0], pair[1]["id"]))
            start = time.perf_counter()
            reranked = rerank_candidates(question, candidates)
            elapsed_ms = round((time.perf_counter() - start) * 1000)
            result = {
                "id": case_id,
                "n_per_method": n,
                "candidate_count": len(candidates),
                "unique_rerank_pairs": len(reranked),
                "evidence_rank": evidence_rank(case["evidence"], reranked),
                "rerank_elapsed_ms": elapsed_ms,
            }
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)

    summary = [{
        "n_per_method": n,
        "sample_count": len(IDS),
        "top4_evidence_hits": sum(result["evidence_rank"] is not None and result["evidence_rank"] <= 4 for result in results if result["n_per_method"] == n),
        "mean_rerank_elapsed_ms": round(sum(result["rerank_elapsed_ms"] for result in results if result["n_per_method"] == n) / len(IDS)),
        "mean_unique_rerank_pairs": round(sum(result["unique_rerank_pairs"] for result in results if result["n_per_method"] == n) / len(IDS), 1),
    } for n in NS]
    output = ROOT / "data/test/candidate_n_benchmark_20261102.json"
    output.write_text(json.dumps({
        "generated_at": datetime.now().astimezone().isoformat(),
        "model": settings.rerank_model,
        "batch_size": settings.rerank_batch_size,
        "sample_ids": IDS,
        "method": "Warm model, paired questions, timed rerank_candidates only; retrieval and answer generation are excluded. N is the candidate count per semantic and keyword method.",
        "summary": summary,
        "cases": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

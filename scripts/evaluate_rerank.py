"""Compare original RRF with a keyword-weighted rerank on 40 evidence cases.

The reranker sees only the question and first-stage rankings. Gold evidence is
used exclusively for evaluation, never to select or score a candidate.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import get_chunks
from scripts.evaluate_api import match_evidence, normalize, source_stem
from scripts.evaluate_retrieval import retrieve


def rerank(
    semantic: list[tuple[float, object]],
    keyword: list[tuple[float, object]],
    keyword_weight: float,
) -> list[tuple[float, object]]:
    """Weighted RRF over the same first-stage candidate pool as original RRF."""
    fused: dict[str, tuple[float, object]] = {}
    for weight, ranked in ((1.0, semantic), (keyword_weight, keyword)):
        for rank, (_, row) in enumerate(ranked, 1):
            previous = fused[row["id"]][0] if row["id"] in fused else 0.0
            fused[row["id"]] = (previous + weight / (60 + rank), row)
    return sorted(fused.values(), key=lambda pair: (-pair[0], pair[1]["id"]))


def evidence_rank(evidence: str, ranked: list[tuple[float, object]]) -> int | None:
    for rank, (_, row) in enumerate(ranked, 1):
        if match_evidence(evidence, row["content"])[0]:
            return rank
    return None


def source_hit(source: str, ranked: list[tuple[float, object]]) -> bool:
    stem = source_stem(source)
    return any(stem in normalize(row["filename"]) or stem in normalize(row["title"]) for _, row in ranked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/test/finance_qa_40.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--keyword-weight", type=float, default=2.0)
    args = parser.parse_args()
    if args.top_k < 1 or args.candidate_k < args.top_k or args.keyword_weight <= 0:
        parser.error("Require top-k >= 1, candidate-k >= top-k, keyword-weight > 0")
    if args.candidate_k > 50:
        parser.error("candidate-k must be <= 50 to match the production candidate pool")
    cases = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not cases:
        parser.error("Input must be a nonempty JSON array")
    ids = [case.get("id") for case in cases]
    if len(set(ids)) != len(ids) or any(not all(case.get(key) for key in ("id", "question", "source", "evidence")) for case in cases):
        parser.error("Every case needs a unique id, question, source and evidence")
    rows = get_chunks(only_valid=True)
    if not rows:
        parser.error("No eligible chunks in database")

    details = []
    for index, case in enumerate(cases, 1):
        original = retrieve(rows, case["question"], args.candidate_k)
        semantic = original["semantic"][: args.top_k]
        keyword = original["keyword"][: args.top_k]
        baseline = original["hybrid"][: args.top_k]
        rescored = rerank(original["semantic"], original["keyword"], args.keyword_weight)
        proposed = rescored[: args.top_k]
        pool_ids = {row["id"] for mode in ("semantic", "keyword") for _, row in original[mode]}
        pool = [(0.0, row) for row in rows if row["id"] in pool_ids]
        baseline_rank = evidence_rank(case["evidence"], baseline)
        rerank_rank = evidence_rank(case["evidence"], proposed)
        detail = {
            "id": case["id"], "question": case["question"], "source": case["source"],
            "evidence": case["evidence"],
            "candidate_pool_has_evidence": evidence_rank(case["evidence"], pool) is not None,
            "semantic_evidence_rank": evidence_rank(case["evidence"], semantic),
            "keyword_evidence_rank": evidence_rank(case["evidence"], keyword),
            "baseline_evidence_rank": baseline_rank,
            "rerank_evidence_rank": rerank_rank,
            "baseline_evidence_hit_at_k": baseline_rank is not None,
            "rerank_evidence_hit_at_k": rerank_rank is not None,
            "baseline_source_hit_at_k": source_hit(case["source"], baseline),
            "rerank_source_hit_at_k": source_hit(case["source"], proposed),
            "semantic_source_hit_at_k": source_hit(case["source"], semantic),
            "keyword_source_hit_at_k": source_hit(case["source"], keyword),
            "baseline": [{"chunk_id": row["id"], "title": row["title"], "score": round(score, 6)} for score, row in baseline],
            "reranked": [{"chunk_id": row["id"], "title": row["title"], "score": round(score, 6)} for score, row in proposed],
        }
        details.append(detail)
        print(f"[{index}/{len(cases)}] {case['id']}: baseline={bool(baseline_rank)} rerank={bool(rerank_rank)}", flush=True)

    count = len(details)
    old = sum(item["baseline_evidence_hit_at_k"] for item in details)
    new = sum(item["rerank_evidence_hit_at_k"] for item in details)
    summary = {
        "case_count": count,
        "candidate_pool_evidence_hit": f"{sum(item['candidate_pool_has_evidence'] for item in details)}/{count}",
        "semantic_evidence_hit_at_k": f"{sum(item['semantic_evidence_rank'] is not None for item in details)}/{count}",
        "keyword_evidence_hit_at_k": f"{sum(item['keyword_evidence_rank'] is not None for item in details)}/{count}",
        "baseline_evidence_hit_at_k": f"{old}/{count}",
        "rerank_evidence_hit_at_k": f"{new}/{count}",
        "baseline_evidence_rate_at_k": round(old / count, 4),
        "rerank_evidence_rate_at_k": round(new / count, 4),
        "delta_percentage_points": round(100 * (new - old) / count, 2),
        "gained_ids": [item["id"] for item in details if item["rerank_evidence_hit_at_k"] and not item["baseline_evidence_hit_at_k"]],
        "lost_ids": [item["id"] for item in details if item["baseline_evidence_hit_at_k"] and not item["rerank_evidence_hit_at_k"]],
        "baseline_source_hit_at_k": f"{sum(item['baseline_source_hit_at_k'] for item in details)}/{count}",
        "rerank_source_hit_at_k": f"{sum(item['rerank_source_hit_at_k'] for item in details)}/{count}",
        "semantic_source_hit_at_k": f"{sum(item['semantic_source_hit_at_k'] for item in details)}/{count}",
        "keyword_source_hit_at_k": f"{sum(item['keyword_source_hit_at_k'] for item in details)}/{count}",
    }
    report = {
        "input": str(args.input), "evaluated_at": datetime.now().astimezone().isoformat(),
        "database_backend": settings.database_backend, "embedding_model": settings.embedding_model,
        "eligible_chunk_count": len(rows), "top_k": args.top_k,
        "candidate_k": args.candidate_k, "reranker": "weighted_rrf",
        "semantic_weight": 1.0, "keyword_weight": args.keyword_weight, "rrf_constant": 60,
        "method": "Both methods use the same semantic top-N and keyword top-N. Baseline uses equal RRF weights; rerank doubles the keyword contribution by default. Gold evidence is used only after ranking. A hit requires the full normalized quote or all ellipsis-separated anchors in order within one returned chunk.",
        "summary": summary, "cases": details,
    }
    output = args.output or ROOT / "data/test" / f"rerank_evaluation_{datetime.now():%Y%m%d-%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

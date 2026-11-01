"""Compare production RRF and a real cross encoder on the 40 evidence questions."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import get_chunks
from app.services.reranker import rerank_candidates
from scripts.evaluate_api import match_evidence
from scripts.evaluate_retrieval import retrieve


def evidence_rank(evidence: str, ranked: list[tuple[float, object]]) -> int | None:
    return next(
        (index for index, (_, row) in enumerate(ranked, 1) if match_evidence(evidence, row["content"])[0]),
        None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/test/finance_qa_40.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    cases = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not cases:
        parser.error("Input must contain a nonempty JSON array")
    rows = get_chunks(only_valid=True)
    if not rows:
        parser.error("No eligible chunks in database")
    output = args.output or ROOT / "data/test" / f"cross_encoder_evaluation_{datetime.now():%Y%m%d-%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    details: list[dict] = []

    for index, case in enumerate(cases, 1):
        started = time.perf_counter()
        original = retrieve(rows, case["question"], 100)
        baseline = original["hybrid"][: args.top_k]
        keyword = original["keyword"][: args.top_k]
        candidates = original["hybrid"]
        reranked = rerank_candidates(case["question"], candidates)
        proposed = reranked[: args.top_k]
        detail = {
            "id": case["id"],
            "question": case["question"],
            "source": case["source"],
            "evidence": case["evidence"],
            "candidate_pool_has_evidence": evidence_rank(case["evidence"], candidates) is not None,
            "keyword_evidence_rank_at_k": evidence_rank(case["evidence"], keyword),
            "baseline_evidence_rank_at_k": evidence_rank(case["evidence"], baseline),
            "cross_encoder_evidence_rank_at_k": evidence_rank(case["evidence"], proposed),
            "cross_encoder_evidence_rank_in_pool": evidence_rank(case["evidence"], reranked),
            "candidate_count": len(candidates),
            "unique_candidate_count": len({row["content"] for _, row in candidates}),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "baseline": [{"chunk_id": row["id"], "title": row["title"], "score": round(score, 6)} for score, row in baseline],
            "cross_encoder": [{"chunk_id": row["id"], "title": row["title"], "score": round(score, 6)} for score, row in proposed],
        }
        details.append(detail)
        print(f"[{index}/{len(cases)}] {case['id']}: baseline={detail['baseline_evidence_rank_at_k']} cross_encoder={detail['cross_encoder_evidence_rank_at_k']} {detail['elapsed_ms']}ms", flush=True)
        # Keep completed cases if a long model run is interrupted.
        output.write_text(json.dumps({"cases": details, "complete": False}, ensure_ascii=False, indent=2), encoding="utf-8")

    count = len(details)
    old = sum(item["baseline_evidence_rank_at_k"] is not None for item in details)
    new = sum(item["cross_encoder_evidence_rank_at_k"] is not None for item in details)
    report = {
        "input": str(args.input),
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "database_backend": settings.database_backend,
        "embedding_model": settings.embedding_model,
        "rerank_model": settings.rerank_model,
        "top_k": args.top_k,
        "candidate_k_per_method": 50,
        "eligible_chunk_count": len(rows),
        "method": "Both methods use the same semantic Top 50 and keyword Top 50 candidates. Baseline uses equal-weight RRF; cross encoder deduplicates identical content and scores each (question, chunk content) pair. Gold evidence is used only for judging, never for scoring.",
        "summary": {
            "case_count": count,
            "candidate_pool_evidence_hit": f"{sum(item['candidate_pool_has_evidence'] for item in details)}/{count}",
            "keyword_evidence_hit_at_k": f"{sum(item['keyword_evidence_rank_at_k'] is not None for item in details)}/{count}",
            "baseline_evidence_hit_at_k": f"{old}/{count}",
            "cross_encoder_evidence_hit_at_k": f"{new}/{count}",
            "delta_percentage_points": round((new - old) * 100 / count, 2),
            "gained_ids": [item["id"] for item in details if item["baseline_evidence_rank_at_k"] is None and item["cross_encoder_evidence_rank_at_k"] is not None],
            "lost_ids": [item["id"] for item in details if item["baseline_evidence_rank_at_k"] is not None and item["cross_encoder_evidence_rank_at_k"] is None],
        },
        "cases": details,
        "complete": True,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

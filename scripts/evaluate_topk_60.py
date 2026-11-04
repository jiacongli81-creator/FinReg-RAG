"""Profile evidence recall at several Top K values on the new 60-question set.

This script does not generate answers. The annotated evidence is used only to
judge ranked source chunks, never to retrieve or rerank candidates.
"""

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
    """Return the first rank containing every evidence anchor in one chunk."""
    return next(
        (rank for rank, (_, row) in enumerate(ranked, 1) if match_evidence(evidence, row["content"])[0]),
        None,
    )


def load_cases(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or len(cases) != 60:
        raise ValueError("The new evaluation set must contain exactly 60 cases")
    required = ("id", "question", "gold_answer", "source", "evidence")
    if any(not isinstance(case, dict) or not all(case.get(key) for key in required) for case in cases):
        raise ValueError(f"Every case needs nonempty fields: {', '.join(required)}")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Case IDs must be unique")
    return cases


def preview(ranked: list[tuple[float, object]], max_k: int) -> list[dict]:
    return [
        {"rank": rank, "chunk_id": row["id"], "title": row["title"], "score": round(float(score), 6)}
        for rank, (score, row) in enumerate(ranked[:max_k], 1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/test/finance_qa_60.json")
    parser.add_argument("--max-k", type=int, default=10, help="Report evidence recall for every K from 1 through max-k")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true", help="Check all gold quotes against the corpus without running retrieval")
    args = parser.parse_args()
    if not 1 <= args.max_k <= 20:
        parser.error("--max-k must be between 1 and 20, matching the API's top_k limit")
    try:
        cases = load_cases(args.input)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    rows = get_chunks(only_valid=True)
    if not rows:
        parser.error("No eligible chunks found in the configured database")
    missing = [
        case["id"]
        for case in cases
        if not any(
            row["filename"] == Path(case["source"].replace("\\", "/")).name
            and match_evidence(case["evidence"], row["content"])[0]
            for row in rows
        )
    ]
    if missing:
        parser.error(f"Annotated evidence is absent from the configured corpus: {missing}")
    if args.validate_only:
        print(f"Validated {len(cases)} evidence quotes in {len(rows)} eligible chunks; retrieval was not run.")
        return 0
    output = args.output or ROOT / "data/test" / f"topk_60_evaluation_{datetime.now():%Y%m%d-%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    details: list[dict] = []

    for index, case in enumerate(cases, 1):
        started = time.perf_counter()
        original = retrieve(rows, case["question"], 100)
        candidates = original["hybrid"]
        reranked = rerank_candidates(case["question"], candidates)
        evidence = case["evidence"]
        detail = {
            "id": case["id"],
            "question": case["question"],
            "gold_answer": case["gold_answer"],
            "source": case["source"],
            "evidence": evidence,
            "corpus_has_evidence": True,
            "candidate_pool_has_evidence": evidence_rank(evidence, candidates) is not None,
            "semantic_evidence_rank": evidence_rank(evidence, original["semantic"]),
            "keyword_evidence_rank": evidence_rank(evidence, original["keyword"]),
            "rrf_evidence_rank": evidence_rank(evidence, candidates),
            "rerank_evidence_rank": evidence_rank(evidence, reranked),
            "candidate_count": len(candidates),
            "unique_candidate_count": len(reranked),
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "rrf_top_chunks": preview(candidates, args.max_k),
            "rerank_top_chunks": preview(reranked, args.max_k),
        }
        details.append(detail)
        output.write_text(json.dumps({"complete": False, "cases": details}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[{index}/{len(cases)}] {case['id']}: "
            f"RRF={detail['rrf_evidence_rank']} rerank={detail['rerank_evidence_rank']}",
            flush=True,
        )

    count = len(details)
    curve = []
    for k in range(1, args.max_k + 1):
        rrf_hits = sum(item["rrf_evidence_rank"] is not None and item["rrf_evidence_rank"] <= k for item in details)
        rerank_hits = sum(item["rerank_evidence_rank"] is not None and item["rerank_evidence_rank"] <= k for item in details)
        curve.append({
            "k": k,
            "rrf_evidence_hit": f"{rrf_hits}/{count}",
            "rrf_evidence_rate": round(rrf_hits / count, 4),
            "rerank_evidence_hit": f"{rerank_hits}/{count}",
            "rerank_evidence_rate": round(rerank_hits / count, 4),
            "rerank_delta_percentage_points": round((rerank_hits - rrf_hits) * 100 / count, 2),
        })

    report = {
        "complete": True,
        "input": str(args.input),
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "database_backend": settings.database_backend,
        "embedding_model": settings.embedding_model,
        "rerank_model": settings.rerank_model,
        "candidate_k_per_method": 50,
        "max_k": args.max_k,
        "eligible_chunk_count": len(rows),
        "method": "The original equal-weight RRF and cross encoder share semantic Top 50 and keyword Top 50 candidates. The cross encoder scores question plus full chunk text after exact-content deduplication. Gold evidence is used only after ranking; a hit requires the complete normalized quote or ordered ellipsis-separated anchors in one chunk.",
        "summary": {
            "case_count": count,
            "corpus_evidence_available": f"{sum(item['corpus_has_evidence'] for item in details)}/{count}",
            "candidate_pool_evidence_hit": f"{sum(item['candidate_pool_has_evidence'] for item in details)}/{count}",
            "mean_elapsed_ms": round(sum(item["elapsed_ms"] for item in details) / count),
            "evidence_recall_curve": curve,
        },
        "cases": details,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

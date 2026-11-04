"""Evaluate actual evidence rank on all 100 cases with a chosen candidate N."""

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
    return next((i for i, (_, row) in enumerate(ranked, 1) if match_evidence(evidence, row["content"])[0]), None)


def candidates_at_n(original: dict, n: int) -> list[tuple[float, object]]:
    fused = {}
    for ranked in (original["semantic"][:n], original["keyword"][:n]):
        for rank, (_, row) in enumerate(ranked, 1):
            prior = fused[row["id"]][0] if row["id"] in fused else 0.0
            fused[row["id"]] = (prior + 1 / (60 + rank), row)
    return sorted(fused.values(), key=lambda pair: (-pair[0], pair[1]["id"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-n", type=int, default=20)
    parser.add_argument("--max-k", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.candidate_n <= 50 or not 1 <= args.max_k <= 20:
        parser.error("candidate N must be 1..50 and max K must be 1..20")
    output = args.output or ROOT / "data/test" / f"topk_100_n{args.candidate_n}_current_20261102.json"
    old = json.loads((ROOT / "data/test/finance_qa_40.json").read_text(encoding="utf-8-sig"))
    new = json.loads((ROOT / "data/test/finance_qa_60.json").read_text(encoding="utf-8-sig"))
    cases = old + new
    if len(old) != 40 or len(new) != 60 or len({case["id"] for case in cases}) != 100:
        parser.error("Expected 40 + 60 unique cases")
    rows = get_chunks(only_valid=True)
    if not rows:
        parser.error("No eligible chunks")
    missing = [case["id"] for case in cases if not any(match_evidence(case["evidence"], row["content"])[0] for row in rows)]
    if missing:
        parser.error(f"Evidence absent from corpus: {missing}")

    details = []
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("candidate_n_per_method") != args.candidate_n or previous.get("max_k") != args.max_k:
            parser.error("Existing output uses different settings")
        details = previous["cases"]
        if [item["id"] for item in details] != [case["id"] for case in cases[:len(details)]]:
            parser.error("Existing output case order differs")
    for index, case in enumerate(cases[len(details):], len(details) + 1):
        start = time.perf_counter()
        original = retrieve(rows, case["question"], 50)
        candidates = candidates_at_n(original, args.candidate_n)
        ranked = rerank_candidates(case["question"], candidates)
        detail = {
            "id": case["id"],
            "cohort": "old_40" if index <= 40 else "new_60",
            "question": case["question"],
            "source": case["source"],
            "evidence": case["evidence"],
            "candidate_pool_has_evidence": evidence_rank(case["evidence"], candidates) is not None,
            "rerank_evidence_rank": evidence_rank(case["evidence"], ranked),
            "candidate_count": len(candidates),
            "unique_candidate_count": len(ranked),
            "elapsed_ms": round((time.perf_counter() - start) * 1000),
            "top_chunks": [
                {"rank": rank, "chunk_id": row["id"], "score": round(score, 6)}
                for rank, (score, row) in enumerate(ranked[:args.max_k], 1)
            ],
        }
        details.append(detail)
        output.write_text(json.dumps({"complete": False, "candidate_n_per_method": args.candidate_n, "max_k": args.max_k, "cases": details}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{index}/100] {case['id']}: rank={detail['rerank_evidence_rank']} elapsed={detail['elapsed_ms']}ms", flush=True)

    curve = []
    for k in range(1, args.max_k + 1):
        old_hits = sum(item["rerank_evidence_rank"] is not None and item["rerank_evidence_rank"] <= k for item in details[:40])
        new_hits = sum(item["rerank_evidence_rank"] is not None and item["rerank_evidence_rank"] <= k for item in details[40:])
        curve.append({"k": k, "old_40_hits": old_hits, "new_60_hits": new_hits, "total_hits": old_hits + new_hits})
    report = {
        "complete": True,
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "candidate_n_per_method": args.candidate_n,
        "max_k": args.max_k,
        "embedding_model": settings.embedding_model,
        "rerank_model": settings.rerank_model,
        "rerank_batch_size": settings.rerank_batch_size,
        "eligible_chunk_count": len(rows),
        "method": "Current pipeline, with semantic Top N and keyword Top N fused by equal-weight RRF, exact-content deduplication, and cross-encoder reranking. A hit requires annotated evidence inside one returned chunk. Gold evidence never influences retrieval or ranking.",
        "summary": {
            "case_count": len(details),
            "candidate_pool_evidence_hits": sum(item["candidate_pool_has_evidence"] for item in details),
            "mean_unique_candidate_count": round(sum(item["unique_candidate_count"] for item in details) / len(details), 1),
            "mean_elapsed_ms": round(sum(item["elapsed_ms"] for item in details) / len(details)),
            "curve": curve,
        },
        "cases": details,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

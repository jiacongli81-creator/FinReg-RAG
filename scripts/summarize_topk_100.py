"""Combine the saved 40-case rerank ranks with the new 60-case Top K run.

The 40-case report is historical; this script does not rerun retrieval or ranking.
Only evidence in one returned chunk counts as a hit, as judged by each input run.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_report(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if not report.get("complete"):
        raise ValueError(f"Evaluation is incomplete: {path}")
    return report


def hit(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, default=ROOT / "data/test/cross_encoder_evaluation_20261101.json")
    parser.add_argument("--new", type=Path, default=ROOT / "data/test/topk_60_evaluation_20261102.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/test/topk_100_summary_20261102.json")
    args = parser.parse_args()

    old = load_report(args.old)
    new = load_report(args.new)
    if len(old["cases"]) != 40 or len(new["cases"]) != 60:
        raise ValueError("Expected 40 historical and 60 new cases")
    if old["rerank_model"] != new["rerank_model"] or old["embedding_model"] != new["embedding_model"]:
        raise ValueError("The reports use different ranking or embedding models")
    if old["eligible_chunk_count"] != new["eligible_chunk_count"]:
        raise ValueError("The reports use different eligible corpus sizes; compare corpus versions before combining")
    if len({case["id"] for case in old["cases"] + new["cases"]}) != 100:
        raise ValueError("The 100 case IDs are not unique")

    old_ranks = {case["id"]: case["cross_encoder_evidence_rank_in_pool"] for case in old["cases"]}
    new_ranks = {case["id"]: case["rerank_evidence_rank"] for case in new["cases"]}
    max_k = min(new["max_k"], 20)
    curve = []
    for k in range(1, max_k + 1):
        old_hits = sum(hit(rank, k) for rank in old_ranks.values())
        new_hits = sum(hit(rank, k) for rank in new_ranks.values())
        curve.append({
            "k": k,
            "historical_40_hits": old_hits,
            "new_60_hits": new_hits,
            "combined_100_hits": old_hits + new_hits,
            "combined_100_recall": round((old_hits + new_hits) / 100, 4),
            "marginal_new_hits": old_hits + new_hits - (curve[-1]["combined_100_hits"] if curve else 0),
        })

    thresholds = {
        f"minimum_k_for_{threshold}_of_100": next((point["k"] for point in curve if point["combined_100_hits"] >= threshold), None)
        for threshold in (90, 95, 98, 99, 100)
    }
    report = {
        "complete": True,
        "generated_at": datetime.now().astimezone().isoformat(),
        "historical_40_report": str(args.old),
        "new_60_report": str(args.new),
        "model": new["rerank_model"],
        "embedding_model": new["embedding_model"],
        "eligible_chunk_count": new["eligible_chunk_count"],
        "method": "A case hits at K when a single returned source chunk contains its annotated evidence. This combines saved ranks from the historical 40-case rerank run with ranks from the new 60-case run. The 40 cases were not rerun. This measures evidence recall, not answer accuracy, latency, or token cost.",
        "curve": curve,
        "thresholds": thresholds,
        "misses_at_max_k": {
            "historical_40": [case_id for case_id, rank in old_ranks.items() if not hit(rank, max_k)],
            "new_60": [case_id for case_id, rank in new_ranks.items() if not hit(rank, max_k)],
        },
        "cases": [
            {"id": case_id, "cohort": "historical_40", "evidence_rank": rank}
            for case_id, rank in old_ranks.items()
        ] + [
            {"id": case_id, "cohort": "new_60", "evidence_rank": rank}
            for case_id, rank in new_ranks.items()
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"curve": curve, "thresholds": thresholds, "misses_at_max_k": report["misses_at_max_k"]}, ensure_ascii=False, indent=2))
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

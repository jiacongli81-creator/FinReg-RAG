"""Compare fast RRF and saved smart reranking on the same 100 evidence cases."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import get_chunks
from scripts.evaluate_retrieval import retrieve
from scripts.evaluate_topk_n_100 import candidates_at_n, evidence_rank


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/test/query_modes_evidence_20261102.json")
    args = parser.parse_args()
    cases = []
    for filename in ("finance_qa_40.json", "finance_qa_60.json"):
        cases.extend(json.loads((ROOT / "data/test" / filename).read_text(encoding="utf-8-sig")))
    smart = json.loads((ROOT / "data/test/topk_100_n20_current_20261102.json").read_text(encoding="utf-8"))
    if len(cases) != 100 or not smart.get("complete") or smart.get("candidate_n_per_method") != 20:
        parser.error("Expected complete, current 100-case N=20 smart report")
    smart_by_id = {row["id"]: row for row in smart["cases"]}
    rows = get_chunks(only_valid=True)
    results = []
    for case in cases:
        original = retrieve(rows, case["question"], 20)
        ranked = candidates_at_n(original, 20)
        results.append({"id": case["id"], "fast_evidence_rank": evidence_rank(case["evidence"], ranked),
                        "smart_evidence_rank": smart_by_id[case["id"]]["rerank_evidence_rank"]})
    summary = {"case_count": len(results), "top_k": 4,
               "fast_evidence_hits": sum(row["fast_evidence_rank"] is not None and row["fast_evidence_rank"] <= 4 for row in results),
               "smart_evidence_hits": sum(row["smart_evidence_rank"] is not None and row["smart_evidence_rank"] <= 4 for row in results)}
    report = {"evaluated_at": datetime.now().astimezone().isoformat(), "candidate_n_per_method": 20,
              "method": "Same 100 annotated evidence cases; fast RRF ranking evaluated now, smart rerank ranks from saved current N=20 report. This measures source evidence recall, not answer correctness.",
              "summary": summary, "cases": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

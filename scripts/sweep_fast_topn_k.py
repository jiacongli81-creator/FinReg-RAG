"""Sweep the fast RRF path over candidate N and returned K on 100 evidence cases."""

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
from scripts.evaluate_api import match_evidence
from scripts.evaluate_retrieval import retrieve
from scripts.evaluate_topk_n_100 import candidates_at_n, evidence_rank

N_VALUES = tuple(range(1, 51))
MAX_K = 10


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/test/fast_topn_k_sweep_20261102.json")
    args = parser.parse_args()
    cases = []
    for name in ("finance_qa_40.json", "finance_qa_60.json"):
        cases.extend(json.loads((ROOT / "data/test" / name).read_text(encoding="utf-8-sig")))
    if len(cases) != 100 or len({case["id"] for case in cases}) != 100:
        parser.error("Expected 100 unique cases")
    rows = get_chunks(only_valid=True)
    if not rows:
        parser.error("No eligible chunks")
    missing = [case["id"] for case in cases if not any(match_evidence(case["evidence"], row["content"])[0] for row in rows)]
    if missing:
        parser.error(f"Evidence absent from eligible corpus: {missing}")
    details = []
    for index, case in enumerate(cases, start=1):
        original = retrieve(rows, case["question"], max(N_VALUES))
        ranks = {}
        for n in N_VALUES:
            ranked = candidates_at_n(original, n)
            ranks[str(n)] = evidence_rank(case["evidence"], ranked)
        details.append({"id": case["id"], "ranks_by_n": ranks})
        if index % 20 == 0:
            print(f"evaluated {index}/{len(cases)}", flush=True)
    matrix = [
        {"n": n, "hits_by_k": {str(k): sum(item["ranks_by_n"][str(n)] is not None
                                              and item["ranks_by_n"][str(n)] <= k for item in details)
                                    for k in range(1, MAX_K + 1)}}
        for n in N_VALUES
    ]
    report = {"evaluated_at": datetime.now().astimezone().isoformat(), "embedding_model": settings.embedding_model,
              "eligible_chunk_count": len(rows), "case_count": len(cases), "n_values": N_VALUES,
              "max_k": MAX_K,
              "method": "For each question, one semantic and keyword Top 50 retrieval, then equal-weight RRF at each N. A hit requires all annotated evidence anchors in one of the first K returned chunks. Evidence is never used for ranking.",
              "matrix": matrix, "cases": details}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"n_values": len(N_VALUES), "max_k": MAX_K,
                      "qualifying_k4": [{"n": row["n"], "hits": row["hits_by_k"]["4"]}
                                        for row in matrix if row["hits_by_k"]["4"] > 85],
                      "selected_rows": [row for row in matrix if row["n"] in (4, 5, 6, 10, 20, 50)]},
                     ensure_ascii=False))
    print(f"Report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

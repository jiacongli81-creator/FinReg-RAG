"""Time real /query calls without printing questions, answers, or source text."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app
from scripts.evaluate_api import match_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fast", "smart"), default="fast")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error("--count must be between 1 and 100")
    cases = []
    for name in ("finance_qa_40.json", "finance_qa_60.json"):
        cases.extend(json.loads((ROOT / "data/test" / name).read_text(encoding="utf-8-sig")))
    cases = cases[:args.count]
    results = []
    with patch("app.services.retrieval.save_history"), TestClient(app) as client:
        for index, case in enumerate(cases, 1):
            started = time.perf_counter()
            try:
                response = client.post("/query", json={"question": case["question"], "mode": args.mode})
                body = response.json()
                hit = any(match_evidence(case["evidence"], item["content"])[0]
                          for item in body.get("sources", [])) if response.status_code == 200 else None
                results.append({"id": case["id"], "status": response.status_code,
                                "mode": body.get("mode"), "source_count": len(body.get("sources", [])),
                                "evidence_hit": hit, "elapsed_ms": body.get("elapsed_ms"),
                                "wall_ms": round((time.perf_counter() - started) * 1000)})
            except Exception as exc:
                results.append({"id": case["id"], "error_type": type(exc).__name__,
                                "wall_ms": round((time.perf_counter() - started) * 1000)})
            if args.count > 20 and index % 20 == 0:
                print(f"evaluated {index}/{args.count}", flush=True)
    successful = [row["elapsed_ms"] for row in results if row.get("status") == 200 and row.get("elapsed_ms") is not None]
    summary = {"mode": args.mode, "sample_count": len(results), "success_count": len(successful),
               "mean_ms": round(statistics.mean(successful)) if successful else None,
               "median_ms": round(statistics.median(successful)) if successful else None,
               "max_ms": max(successful) if successful else None,
               "under_2500_ms": sum(ms < 2500 for ms in successful),
               "evidence_hits": sum(row.get("evidence_hit") is True for row in results)}
    report = {"summary": summary, "results": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if len(successful) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

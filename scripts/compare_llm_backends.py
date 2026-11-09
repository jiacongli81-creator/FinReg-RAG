"""Benchmark the running API against fixed QA cases, cleaning generated history."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from evaluate_api import match_evidence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IDS = "qa-01,qa-08,qa-22,qa-29,qa-36,qa-43,qa-50,qa-57,qa-64,qa-71,qa-85,qa-92"


def request(url: str, method: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers=headers, method=method),
        timeout=240,
    ) as response:
        return json.load(response)


def summarize(rows: list[dict], mode: str) -> dict:
    selected = [row for row in rows if row["mode"] == mode]
    good = [row for row in selected if row.get("status") == 200]
    times = [row["wall_ms"] for row in good]
    return {
        "count": len(selected),
        "success": len(good),
        "median_wall_ms": round(statistics.median(times)) if times else None,
        "mean_wall_ms": round(statistics.mean(times)) if times else None,
        "min_wall_ms": min(times) if times else None,
        "max_wall_ms": max(times) if times else None,
        "evidence_hits": sum(row.get("evidence_hit") is True for row in good),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--label", required=True)
    parser.add_argument("--case-ids", default=DEFAULT_IDS)
    parser.add_argument("--modes", default="fast,smart", help="Comma-separated: fast,smart")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    by_id = {}
    for filename in ("finance_qa_40.json", "finance_qa_60.json"):
        for case in json.loads((ROOT / "data/test" / filename).read_text(encoding="utf-8-sig")):
            by_id[case["id"]] = case
    case_ids = [item.strip() for item in args.case_ids.split(",") if item.strip()]
    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    if not modes or any(item not in ("fast", "smart") for item in modes):
        parser.error("--modes must contain fast and/or smart")
    cases = [by_id[item] for item in case_ids]
    base_url = args.base_url.rstrip("/")
    health = request(base_url + "/health", "GET")
    report = {
        "label": args.label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "llm_provider": health["llm_provider"],
        "embedding_model": health["embedding_model"],
        "vector_backend": health["vector_backend"],
        "cases": case_ids,
        "rows": [],
    }
    for mode in modes:
        for index, case in enumerate(cases, 1):
            started = time.perf_counter()
            row = {
                "id": case["id"],
                "mode": mode,
                "question": case["question"],
                "gold_answer": case["gold_answer"],
                "evidence": case["evidence"],
            }
            history_id = None
            try:
                answer = request(base_url + "/query", "POST", {
                    "question": case["question"], "mode": mode, "only_valid": True,
                })
                history_id = answer.get("history_id")
                sources = answer["sources"]
                row.update({
                    "status": 200,
                    "api_elapsed_ms": answer["elapsed_ms"],
                    "answer": answer["answer"],
                    "sources": sources,
                    "source_count": len(sources),
                    "evidence_hit": any(match_evidence(case["evidence"], item["content"])[0]
                                        for item in sources),
                })
            except urllib.error.HTTPError as exc:
                row.update({"status": exc.code, "error": exc.read().decode("utf-8", errors="replace")[:500]})
            except Exception as exc:
                row.update({"status": 0, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                row["wall_ms"] = round((time.perf_counter() - started) * 1000)
                if history_id:
                    try:
                        request(base_url + f"/history/{history_id}", "DELETE")
                    except Exception as exc:
                        row["history_cleanup_error"] = str(exc)
                report["rows"].append(row)
                report["summary"] = {name: summarize(report["rows"], name) for name in ("fast", "smart")}
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"{args.label} {mode} {index}/{len(cases)} {case['id']} status={row['status']} "
                      f"wall_ms={row['wall_ms']} evidence={row.get('evidence_hit')}", flush=True)
    return 0 if all(row["status"] == 200 for row in report["rows"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

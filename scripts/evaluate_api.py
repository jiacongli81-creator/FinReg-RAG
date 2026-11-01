"""Evaluate API answers and check annotated evidence in returned source chunks.

Use --from-report to re-score a saved API run without calling the API again.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.keywords import keywords
from app.db import get_chunks


def normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).lower() if c.isalnum())


def source_stem(source: str) -> str:
    hint = source.split("，", 1)[0].split("（", 1)[0].split("(", 1)[0]
    return normalize(Path(hint.replace("\\", "/")).stem)


def evidence_segments(evidence: str) -> list[str]:
    """Split editorial ellipses; all literal anchors must match in order."""
    return [segment for part in re.split(r"…+|\.{3,}|⋯+", evidence) if (segment := normalize(part))]


def match_evidence(evidence: str, content: str) -> tuple[bool, int]:
    """Require the entire quote, or every ellipsis-separated anchor, in one chunk."""
    segments = evidence_segments(evidence)
    if not segments:
        return False, 0
    haystack = normalize(content)
    offset = 0
    for index, segment in enumerate(segments):
        found = haystack.find(segment, offset)
        if found < 0:
            return False, index
        offset = found + len(segment)
    return True, len(segments)


def evaluate_case(case: dict, response: dict) -> dict:
    answer = str(response.get("answer", ""))
    sources = response.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("Response sources must be a list")
    gold = str(case["gold_answer"])
    terms = sorted(set(case.get("gold_answer_terms") or (t for t in keywords(gold) if len(t) > 1)))
    answer_normalized = normalize(answer)
    gold_normalized = normalize(gold)
    coverage = sum(normalize(t) in answer_normalized for t in terms) / len(terms) if terms else None
    expected = source_stem(str(case["source"]))
    source_hit = any(expected in normalize(str(s.get("title", ""))) for s in sources) if expected else None
    evidence = str(case["evidence"])
    checked_sources = []
    for rank, source in enumerate(sources, 1):
        matched, anchors_found = match_evidence(evidence, str(source.get("content", "")))
        checked_sources.append({
            "rank": rank,
            "title": source.get("title"),
            "chunk_id": source.get("chunk_id"),
            "evidence_match": matched,
            "ordered_anchors_found": anchors_found,
            "content_preview": str(source.get("content", ""))[:220],
        })
    matched_source = next((source for source in checked_sources if source["evidence_match"]), None)
    return {
        "id": case["id"],
        "question": case["question"],
        "gold_answer": gold,
        "answer": answer,
        "gold_answer_exact_in_answer": bool(gold_normalized and gold_normalized in answer_normalized),
        "gold_term_coverage_in_answer": round(coverage, 4) if coverage is not None else None,
        "expected_source_hit_at_k": source_hit,
        "evidence_hit_at_k": matched_source is not None,
        "evidence_match_rank": matched_source["rank"] if matched_source else None,
        "evidence_matched_chunk_id": matched_source["chunk_id"] if matched_source else None,
        "evidence_anchor_count": len(evidence_segments(evidence)),
        "expected_source": case["source"],
        "evidence": evidence,
        "returned_sources": checked_sources,
        "elapsed_ms": response.get("elapsed_ms"),
        "llm_provider": response.get("llm_provider"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/test/finance_qa_40.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-cases", type=int, default=None, help="Optional smoke-test limit")
    parser.add_argument("--from-report", type=Path, help="Re-score saved answers and chunk IDs; never call /query")
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20 or args.timeout <= 0 or (args.max_cases is not None and args.max_cases < 1):
        parser.error("top-k must be 1..20; timeout and max-cases must be positive")
    cases = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if not isinstance(cases, list) or not cases:
        parser.error("input must contain a nonempty JSON array")
    if args.max_cases is not None:
        cases = cases[:args.max_cases]
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)) or any(not all(case.get(k) for k in ("id", "question", "gold_answer", "source", "evidence")) for case in cases):
        parser.error("cases need unique IDs and question, gold_answer, source, evidence")

    cached = {}
    chunks_by_id = {}
    if args.from_report:
        prior = json.loads(args.from_report.read_text(encoding="utf-8-sig"))
        cached = {item["id"]: item for item in prior["cases"]}
        chunks_by_id = {row["id"]: row for row in get_chunks(only_valid=True)}
        missing = [case["id"] for case in cases if case["id"] not in cached or cached[case["id"]].get("status") != "ok"]
        if missing:
            parser.error(f"saved report lacks successful cases: {missing}")
        chunk_ids = [source["chunk_id"] for case in cases for source in cached[case["id"]]["returned_sources"]]
        unknown = sorted(set(chunk_ids) - chunks_by_id.keys())
        if unknown:
            parser.error(f"saved source chunks missing from current database: {unknown[:5]}")

    results = []
    started = time.monotonic()
    for index, case in enumerate(cases, 1):
        try:
            if args.from_report:
                saved = cached[case["id"]]
                response = {
                    "answer": saved["answer"],
                    "elapsed_ms": saved.get("elapsed_ms"),
                    "llm_provider": saved.get("llm_provider"),
                    "sources": [
                        {"title": source["title"], "chunk_id": source["chunk_id"],
                         "content": chunks_by_id[source["chunk_id"]]["content"]}
                        for source in saved["returned_sources"]
                    ],
                }
            else:
                payload = json.dumps({"question": case["question"], "top_k": args.top_k, "only_valid": True}, ensure_ascii=False).encode("utf-8")
                request = Request(args.base_url.rstrip("/") + "/query", data=payload, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
                with urlopen(request, timeout=args.timeout) as handle:
                    response = json.load(handle)
            result = evaluate_case(case, response)
            result["status"] = "ok"
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, OSError) as exc:
            result = {"id": case["id"], "question": case["question"], "status": "error", "error": str(exc)}
        results.append(result)
        print(f"[{index}/{len(cases)}] {case['id']}: {result['status']}", flush=True)

    valid = [r for r in results if r["status"] == "ok"]
    source_hits = [r["expected_source_hit_at_k"] for r in valid if r["expected_source_hit_at_k"] is not None]
    evidence_hits = sum(r["evidence_hit_at_k"] for r in valid)
    coverages = [r["gold_term_coverage_in_answer"] for r in valid if r["gold_term_coverage_in_answer"] is not None]
    report = {
        "input": str(args.input),
        "base_url": args.base_url,
        "rescore_of": str(args.from_report) if args.from_report else None,
        "source_content_origin": "current_database_by_reported_chunk_id" if args.from_report else "original_api_response",
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "top_k": args.top_k,
        "metrics_note": "Evidence hit requires the full normalized quote in one returned source chunk; editorial ellipses split the quote into ordered exact anchors. This measures evidence retrieval, not whether the generated answer is correct.",
        "summary": {
            "case_count": len(cases),
            "api_success": f"{len(valid)}/{len(cases)}",
            "evidence_hit_at_k": f"{evidence_hits}/{len(valid)}",
            "evidence_hit_rate_at_k": round(evidence_hits / len(valid), 4) if valid else None,
            "expected_source_hit_at_k": f"{sum(source_hits)}/{len(source_hits)}",
            "expected_source_hit_rate_at_k": round(sum(source_hits) / len(source_hits), 4) if source_hits else None,
            "mean_gold_term_coverage_in_answer": round(sum(coverages) / len(coverages), 4) if coverages else None,
            "gold_answer_exact_in_answer": f"{sum(r['gold_answer_exact_in_answer'] for r in valid)}/{len(valid)}",
            "wall_seconds": round(time.monotonic() - started, 2),
        },
        "cases": results,
    }
    prefix = "api_evidence_evaluation" if args.from_report else "api_evaluation"
    output = args.output or ROOT / "data/test" / f"{prefix}_{datetime.now():%Y%m%d-%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0 if len(valid) == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())

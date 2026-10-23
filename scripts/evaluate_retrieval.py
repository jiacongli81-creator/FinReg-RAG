"""Evaluate semantic, jieba keyword, and RRF retrieval on data/test questions."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.db import get_chunks
from app.services.embeddings import cosine, embed
from app.services.keywords import keywords, rank_keywords


QUESTION_START = re.compile(r"(?<!\d)(\d+)[、.]")
ANSWER_MARK = re.compile(r"[（(]\s*([A-D])\s*[）)]", re.IGNORECASE)
OPTION_MARK = re.compile(r"([A-D])[.、]\s*", re.IGNORECASE)
STOP_TERMS = {"一个", "什么", "哪些", "我国", "中国", "进行", "可以", "主要", "包括", "其中", "规定", "要求", "根据", "关于", "以下", "如何"}


def parse_dataset(path: Path) -> list[dict[str, object]]:
    raw = path.read_text(encoding="utf-8-sig")
    starts = list(QUESTION_START.finditer(raw))
    cases: list[dict[str, object]] = []
    for index, match in enumerate(starts):
        block_end = starts[index + 1].start() if index + 1 < len(starts) else len(raw)
        block = raw[match.end() : block_end].strip()
        if not block:
            continue

        answer_marker = ANSWER_MARK.search(block)
        answer_separator = re.search(r"答\s*[:：]", block)
        if answer_marker:
            stem = block[: answer_marker.start()].strip()
            tail = block[answer_marker.end() :].strip()
            option_marks = list(OPTION_MARK.finditer(tail))
            options: dict[str, str] = {}
            for option_index, option_match in enumerate(option_marks):
                option_end = option_marks[option_index + 1].start() if option_index + 1 < len(option_marks) else len(tail)
                options[option_match.group(1).upper()] = tail[option_match.end() : option_end].strip()
            correct = answer_marker.group(1).upper()
            gold = options.get(correct, "")
            if not stem or not gold or len(options) < 2:
                raise ValueError(f"Could not parse multiple-choice item {match.group(1)}")
            cases.append({"id": f"mc-{match.group(1)}", "type": "multiple_choice", "question": stem, "gold_answer": gold, "gold_answer_terms": [], "answer_letter": correct, "options": options})
        elif answer_separator:
            question = block[: answer_separator.start()].strip()
            gold = block[answer_separator.end() :].strip()
            if not question or not gold:
                raise ValueError(f"Could not parse question-answer item {match.group(1)}")
            gold_terms = sorted({term for term in keywords(gold) if len(term) > 1 and term not in STOP_TERMS})
            cases.append({"id": f"qa-{match.group(1)}", "type": "short_answer", "question": question, "gold_answer": gold, "gold_answer_terms": gold_terms, "answer_letter": None, "options": {}})
        else:
            raise ValueError(f"Unrecognized item {match.group(1)}: {block[:100]}")
    return cases


def normalized(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKC", text).lower() if char.isalnum())


def retrieve(rows: list, question: str, top_k: int) -> dict[str, list[tuple[float, object]]]:
    query_vector = embed(question)
    semantic = [(cosine(query_vector, json.loads(row["embedding"])), row) for row in rows]
    semantic.sort(key=lambda item: (-item[0], item[1]["id"]))
    keyword = rank_keywords(question, rows)
    fused: dict[str, tuple[float, object]] = {}
    for ranked in (semantic[:50], keyword):
        for rank, (_, row) in enumerate(ranked, 1):
            previous = fused[row["id"]][0] if row["id"] in fused else 0.0
            fused[row["id"]] = (previous + 1 / (60 + rank), row)
    hybrid = sorted(fused.values(), key=lambda item: (-item[0], item[1]["id"]))
    return {"semantic": semantic[:top_k], "keyword": keyword[:top_k], "hybrid": hybrid[:top_k]}


def answer_coverage(case: dict[str, object], ranked: list[tuple[float, object]]) -> tuple[float, bool | None]:
    retrieved = "\n".join(row["content"] for _, row in ranked)
    if case["type"] == "multiple_choice":
        gold = normalized(str(case["gold_answer"]))
        return (1.0 if gold and gold in normalized(retrieved) else 0.0, bool(gold and gold in normalized(retrieved)))
    gold_terms = case["gold_answer_terms"]
    if not gold_terms:
        return 0.0, None
    normalized_retrieved = normalized(retrieved)
    found = sum(normalized(term) in normalized_retrieved for term in gold_terms)
    return found / len(gold_terms), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "data" / "test" / "评测集.txt")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data" / "test")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    cases = parse_dataset(args.input)
    rows = get_chunks(only_valid=True)
    if not rows:
        print("No eligible document chunks found.", file=sys.stderr)
        return 2
    dimensions = {len(json.loads(row["embedding"])) for row in rows}
    if len(dimensions) != 1:
        print(f"Mixed embedding dimensions in database: {sorted(dimensions)}", file=sys.stderr)
        return 2

    summaries: dict[str, dict[str, object]] = {}
    for mode in ("semantic", "keyword", "hybrid"):
        summaries[mode] = {"multiple_choice": Counter(), "short_answer_coverage_sum": 0.0, "short_answer_count": 0}

    details = []
    for case in cases:
        ranked_by_mode = retrieve(rows, str(case["question"]), args.top_k)
        detail: dict[str, object] = {key: value for key, value in case.items() if key != "options"}
        detail["options"] = case["options"]
        detail["results"] = {}
        for mode, ranked in ranked_by_mode.items():
            coverage, exact_hit = answer_coverage(case, ranked)
            mode_summary = summaries[mode]
            if case["type"] == "multiple_choice":
                mode_summary["multiple_choice"]["total"] += 1
                mode_summary["multiple_choice"]["answer_hit"] += int(bool(exact_hit))
            else:
                mode_summary["short_answer_coverage_sum"] += coverage
                mode_summary["short_answer_count"] += 1
            detail["results"][mode] = {
                "answer_coverage_at_k": round(coverage, 4),
                "exact_answer_hit_at_k": exact_hit,
                "sources": [
                    {"title": row["title"], "page": row["page"], "chunk_id": row["id"], "score": round(score, 6), "content_preview": row["content"][:180]}
                    for score, row in ranked
                ],
            }
        details.append(detail)

    summary_out = {}
    for mode, values in summaries.items():
        mc = values["multiple_choice"]
        qa_count = values["short_answer_count"]
        summary_out[mode] = {
            "multiple_choice_answer_hit_at_k": f"{mc['answer_hit']}/{mc['total']}",
            "multiple_choice_hit_rate_at_k": round(mc["answer_hit"] / mc["total"], 4) if mc["total"] else None,
            "short_answer_mean_gold_term_coverage_at_k": round(values["short_answer_coverage_sum"] / qa_count, 4) if qa_count else None,
            "short_answer_count": qa_count,
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    cases_path = args.output_dir / "evaluation_cases.json"
    report_path = args.output_dir / f"retrieval_evaluation_{timestamp}.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "input": str(args.input),
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": next(iter(dimensions)),
        "eligible_chunk_count": len(rows),
        "case_count": len(cases),
        "top_k": args.top_k,
        "metrics_note": "Gold documents/chunks were not annotated in the source set. Multiple-choice answer hit and short-answer gold-term coverage are answer-evidence proxy metrics, not labeled Recall@K or answer correctness.",
        "summary": summary_out,
        "cases": details,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Parsed cases: {len(cases)} (multiple-choice={sum(c['type'] == 'multiple_choice' for c in cases)}, short-answer={sum(c['type'] == 'short_answer' for c in cases)})")
    print(f"Chunks evaluated: {len(rows)}; embedding dimensions: {next(iter(dimensions))}; top_k={args.top_k}")
    for mode, metrics in summary_out.items():
        print(f"{mode}: MC answer hit {metrics['multiple_choice_answer_hit_at_k']} ({metrics['multiple_choice_hit_rate_at_k']}), QA mean answer-term coverage {metrics['short_answer_mean_gold_term_coverage_at_k']}")
    print(f"Structured cases: {cases_path}")
    print(f"Detailed report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

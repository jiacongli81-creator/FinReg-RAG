"""Check how smaller semantic/keyword candidate pools affect evidence availability.

The saved N=50 reranker output is reused. This script embeds questions but does
not rerun the cross encoder, so its Top K preservation result is a projection.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.db import get_chunks
from app.services.embeddings import cosine, embed
from app.services.keywords import rank_keywords
from scripts.evaluate_api import match_evidence

NS = (10, 20, 30, 40, 50)


def main() -> int:
    old = json.loads((ROOT / "data/test/cross_encoder_evaluation_20261101.json").read_text(encoding="utf-8"))
    new = json.loads((ROOT / "data/test/topk_60_evaluation_20261102.json").read_text(encoding="utf-8"))
    if not old.get("complete") or not new.get("complete"):
        raise ValueError("Both saved N=50 reports must be complete")
    cases = [(case, "old") for case in old["cases"]] + [(case, "new") for case in new["cases"]]
    rows = get_chunks(only_valid=True)
    by_id = {row["id"]: row for row in rows}
    if len(cases) != 100 or len(rows) != old["eligible_chunk_count"] or len(rows) != new["eligible_chunk_count"]:
        raise ValueError("Case or corpus counts differ from the saved reports")

    stats = {n: {"pool_hits": 0, "preserved_saved_top4_hits": 0, "candidate_counts": [], "unique_counts": [], "pool_misses": [], "lost_saved_top4_hits": []} for n in NS}
    for index, (case, cohort) in enumerate(cases, 1):
        question, evidence = case["question"], case["evidence"]
        rank = case["cross_encoder_evidence_rank_in_pool"] if cohort == "old" else case["rerank_evidence_rank"]
        preview = case["cross_encoder"] if cohort == "old" else case["rerank_top_chunks"]
        saved_winner_content = None
        if rank is not None and rank <= 4:
            winner = by_id[preview[rank - 1]["chunk_id"]]
            if not match_evidence(evidence, winner["content"])[0]:
                raise ValueError(f"Saved winner does not contain evidence: {case['id']}")
            saved_winner_content = winner["content"]

        query_vector = embed(question)
        semantic = sorted(rows, key=lambda row: (-cosine(query_vector, json.loads(row["embedding"])), row["id"]))[: max(NS)]
        keyword = [row for _, row in rank_keywords(question, rows, limit=max(NS))]
        for n in NS:
            pool = {row["id"]: row for row in semantic[:n] + keyword[:n]}
            contents = {row["content"] for row in pool.values()}
            result = stats[n]
            result["candidate_counts"].append(len(pool))
            result["unique_counts"].append(len(contents))
            if any(match_evidence(evidence, content)[0] for content in contents):
                result["pool_hits"] += 1
            else:
                result["pool_misses"].append(case["id"])
            if saved_winner_content is not None:
                if saved_winner_content in contents:
                    result["preserved_saved_top4_hits"] += 1
                else:
                    result["lost_saved_top4_hits"].append(case["id"])
        print(f"[{index}/100] {case['id']}", flush=True)

    summary = []
    for n in NS:
        result = stats[n]
        summary.append({
            "n_per_method": n,
            "pool_evidence_hits": result["pool_hits"],
            "saved_n50_top4_hits_preserved": result["preserved_saved_top4_hits"],
            "mean_candidate_count": round(sum(result["candidate_counts"]) / 100, 1),
            "mean_unique_rerank_pairs": round(sum(result["unique_counts"]) / 100, 1),
            "pool_miss_ids": result["pool_misses"],
            "lost_saved_top4_hit_ids": result["lost_saved_top4_hits"],
        })
    output = ROOT / "data/test/candidate_n_analysis_20261102.json"
    output.write_text(json.dumps({
        "generated_at": datetime.now().astimezone().isoformat(),
        "embedding_model": settings.embedding_model,
        "corpus_chunk_count": len(rows),
        "case_count": len(cases),
        "saved_n50_top4_hits": 98,
        "method": "For each N, form the union of semantic Top N and keyword Top N. Pool hit requires a single candidate chunk to contain annotated evidence. Saved N=50 Top 4 hits are projected as preserved when their evidence-containing chunk content is still in the smaller pool; the cross encoder is not rerun here.",
        "summary": summary,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

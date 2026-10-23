import json

from ..config import settings
from ..db import get_chunks, save_history
from .embeddings import cosine, embed
from .keywords import rank_keywords
from .llm import generate_answer


def query(question: str, top_k: int | None, only_valid: bool) -> tuple[str, str, list[dict]]:
    rows = get_chunks(only_valid)
    query_vector = embed(question)
    vector_candidates = []
    for row in rows:
        score = cosine(query_vector, json.loads(row["embedding"]))
        vector_candidates.append((score, row))
    vector_candidates.sort(key=lambda item: (-item[0], item[1]["id"]))
    keyword_candidates = rank_keywords(question, rows)

    # Reciprocal rank fusion keeps keyword and vector scores on comparable scales.
    fused: dict[str, tuple[float, object]] = {}
    for candidates in (vector_candidates[:50], keyword_candidates):
        for rank, (_, row) in enumerate(candidates, start=1):
            old_score = fused[row["id"]][0] if row["id"] in fused else 0.0
            fused[row["id"]] = (old_score + 1 / (60 + rank), row)
    selected = sorted(fused.values(), key=lambda item: (-item[0], item[1]["id"]))[: top_k or settings.retrieval_top_k]
    sources = [
        {
            "document_id": row["document_id"],
            "title": row["title"],
            "chunk_id": row["id"],
            "page": row["page"],
            "section": row["section"],
            "score": round(score, 4),
            "content": row["content"],
            "effective_date": row["effective_date"],
            "validity": row["validity"],
        }
        for score, row in selected
    ]
    answer, confidence = generate_answer(question, sources)
    save_history(question, answer, sources)
    return answer, confidence, sources

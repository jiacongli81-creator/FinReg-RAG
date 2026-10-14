import json

from ..config import settings
from ..db import get_chunks, save_history
from .embeddings import cosine, embed
from .llm import generate_answer


def query(question: str, top_k: int | None, only_valid: bool) -> tuple[str, str, list[dict]]:
    query_vector = embed(question)
    candidates = []
    for row in get_chunks(only_valid):
        score = cosine(query_vector, json.loads(row["embedding"]))
        candidates.append((score, row))
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[: top_k or settings.retrieval_top_k]
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

"""Standalone keyword search over ingested knowledge-base chunks."""

from ..db import get_search_chunks
from .keywords import rank_keywords


def search_keywords(query: str, limit: int = 20, only_valid: bool = True) -> list[dict]:
    ranked = rank_keywords(query.strip(), get_search_chunks(only_valid), limit=limit)
    return [
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
        for score, row in ranked
    ]

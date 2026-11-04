"""The existing RAG algorithm, orchestrated as a LangChain LCEL pipeline."""

import json
import logging
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from ..config import settings
from ..db import get_chunks, save_history
from .embeddings import cosine, embed
from .keywords import rank_keywords
from .llm import generate_answer, generate_fast_answer
from .reranker import rerank_candidates
from .vector_store import search_vectors

logger = logging.getLogger(__name__)


def _retrieve(state: dict) -> dict:
    rows = get_chunks(state["only_valid"])
    candidate_n = (settings.retrieval_fast_candidate_n if state["mode"] == "fast"
                   else settings.retrieval_candidate_n)
    if candidate_n < 1:
        raise RuntimeError("Retrieval candidate N must be positive")
    query_vector = embed(state["question"])
    if getattr(settings, "vector_backend", "local") == "milvus":
        by_id = {row["id"]: row for row in rows}
        vector_candidates = [(score, by_id[chunk_id]) for chunk_id, score in
                             search_vectors(query_vector, candidate_n, state["only_valid"])
                             if chunk_id in by_id]
    elif getattr(settings, "vector_backend", "local") == "local":
        vector_candidates = [
            (cosine(query_vector, json.loads(row["embedding"])), row) for row in rows
        ]
        vector_candidates.sort(key=lambda item: (-item[0], item[1]["id"]))
    else:
        raise RuntimeError(f"不支持的 VECTOR_BACKEND: {settings.vector_backend}")
    keyword_candidates = rank_keywords(state["question"], rows, limit=candidate_n)

    # Fuse semantic and keyword Top N with the existing RRF formula.
    fused: dict[str, tuple[float, object]] = {}
    for candidates in (vector_candidates[:candidate_n], keyword_candidates):
        for rank, (_, row) in enumerate(candidates, start=1):
            old_score = fused[row["id"]][0] if row["id"] in fused else 0.0
            fused[row["id"]] = (old_score + 1 / (60 + rank), row)
    ranked = sorted(fused.values(), key=lambda item: (-item[0], item[1]["id"]))
    return {**state, "ranked": ranked}


def warm_fast_retrieval() -> None:
    """Move keyword and local embedding model warmup to application startup."""
    rows = get_chunks(True)
    if rows:
        rank_keywords("金融", rows, limit=1)
    if settings.embedding_provider == "ollama":
        try:
            embed("金融制度问答预热")
        except RuntimeError as exc:
            logger.warning("Embedding warmup skipped: %s", exc)


def _select_documents(state: dict) -> dict:
    ranked = state["ranked"]
    if state["mode"] == "smart":
        if not settings.rerank_enabled:
            raise RuntimeError("智能档需要启用 RERANK_ENABLED")
        ranked = rerank_candidates(state["question"], ranked)
    default_top_k = settings.retrieval_fast_top_k if state["mode"] == "fast" else settings.retrieval_top_k
    selected = ranked[: state["top_k"] or default_top_k]
    documents = [
        Document(
            page_content=row["content"],
            metadata={
                "document_id": row["document_id"],
                "title": row["title"],
                "chunk_id": row["id"],
                "page": row["page"],
                "section": row["section"],
                "score": round(score, 4),
                "effective_date": row["effective_date"],
                "validity": row["validity"],
            },
        )
        for score, row in selected
    ]
    return {"question": state["question"], "documents": documents, "mode": state["mode"]}


def _generate(state: dict) -> dict:
    sources = [
        {**document.metadata, "content": document.page_content}
        for document in state["documents"]
    ]
    generator = generate_fast_answer if state["mode"] == "fast" else generate_answer
    answer, confidence = generator(state["question"], sources)
    return {"question": state["question"], "answer": answer, "confidence": confidence, "sources": sources}


def _save(state: dict) -> dict:
    return {**state, "history_id": save_history(state["question"], state["answer"], state["sources"])}


@lru_cache(maxsize=1)
def question_answer_chain():
    """Compose retrieval, reranking, answering and persistence with LangChain."""
    return (
        RunnableLambda(_retrieve)
        | RunnableLambda(_select_documents)
        | RunnableLambda(_generate)
        | RunnableLambda(_save)
    )


def query(question: str, top_k: int | None, only_valid: bool, mode: str = "fast") -> tuple[str, str, list[dict], int]:
    if mode not in {"fast", "smart"}:
        raise ValueError(f"Unsupported query mode: {mode}")
    result = question_answer_chain().invoke(
        {"question": question, "top_k": top_k, "only_valid": only_valid, "mode": mode}
    )
    return result["answer"], result["confidence"], result["sources"], result["history_id"]

"""The fast and smart paths must choose different ranking behavior."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas import QueryRequest
from app.services import retrieval
from app.services.llm import generate_fast_answer


def candidate(chunk_id: str) -> tuple[float, dict]:
    return 0.5, {
        "id": chunk_id, "document_id": "doc", "title": "title",
        "content": chunk_id, "page": None, "section": None,
        "effective_date": None, "validity": "valid",
    }


class QueryModeTests(unittest.TestCase):
    def setUp(self):
        self.state = {"question": "test", "top_k": 1,
                      "ranked": [candidate("rrf-first"), candidate("reranked-first")]}

    def test_fast_skips_reranker(self):
        with patch.object(retrieval, "rerank_candidates") as rerank:
            selected = retrieval._select_documents({**self.state, "mode": "fast"})
        rerank.assert_not_called()
        self.assertEqual(selected["documents"][0].metadata["chunk_id"], "rrf-first")

    def test_fast_uses_its_own_candidate_n_and_default_k(self):
        six = [candidate(str(index)) for index in range(6)]
        with patch.object(retrieval, "settings", SimpleNamespace(
            retrieval_fast_candidate_n=5, retrieval_candidate_n=20,
            retrieval_fast_top_k=5, retrieval_top_k=4)):
            with patch.object(retrieval, "get_chunks", return_value=[]):
                with patch.object(retrieval, "embed", return_value=[]):
                    with patch.object(retrieval, "rank_keywords", return_value=[]) as keywords:
                        retrieval._retrieve({"question": "test", "only_valid": True, "mode": "fast"})
                    keywords.assert_called_once_with("test", [], limit=5)
            selected = retrieval._select_documents({**self.state, "mode": "fast", "top_k": None, "ranked": six})
            self.assertEqual(len(selected["documents"]), 5)
            overridden = retrieval._select_documents({**self.state, "mode": "fast", "top_k": 2, "ranked": six})
            self.assertEqual(len(overridden["documents"]), 2)

    def test_smart_uses_reranker(self):
        with patch.object(retrieval, "rerank_candidates", return_value=list(reversed(self.state["ranked"]))) as rerank:
            selected = retrieval._select_documents({**self.state, "mode": "smart"})
        rerank.assert_called_once_with("test", self.state["ranked"])
        self.assertEqual(selected["documents"][0].metadata["chunk_id"], "reranked-first")

    def test_smart_keeps_existing_candidate_n_and_default_k(self):
        six = [candidate(str(index)) for index in range(6)]
        with patch.object(retrieval, "settings", SimpleNamespace(
            retrieval_fast_candidate_n=5, retrieval_candidate_n=20,
            retrieval_fast_top_k=5, retrieval_top_k=4, rerank_enabled=True)):
            with patch.object(retrieval, "get_chunks", return_value=[]):
                with patch.object(retrieval, "embed", return_value=[]):
                    with patch.object(retrieval, "rank_keywords", return_value=[]) as keywords:
                        retrieval._retrieve({"question": "test", "only_valid": True, "mode": "smart"})
                    keywords.assert_called_once_with("test", [], limit=20)
            with patch.object(retrieval, "rerank_candidates", return_value=six):
                selected = retrieval._select_documents({**self.state, "mode": "smart", "top_k": None, "ranked": six})
            self.assertEqual(len(selected["documents"]), 4)

    def test_disabled_smart_mode_fails_explicitly(self):
        with patch.object(retrieval, "settings", SimpleNamespace(rerank_enabled=False, retrieval_top_k=4)):
            with self.assertRaisesRegex(RuntimeError, "RERANK_ENABLED"):
                retrieval._select_documents({**self.state, "mode": "smart"})

    def test_request_defaults_to_fast_and_rejects_unknown_mode(self):
        self.assertEqual(QueryRequest(question="test").mode, "fast")
        with self.assertRaises(ValidationError):
            QueryRequest(question="test", mode="unknown")

    def test_fast_answer_is_local_excerpt_with_citation(self):
        sources = [{"content": "普通内容。商业银行应当保护存款人的合法权益。"}]
        answer, confidence = generate_fast_answer("如何保护存款人权益", sources)
        self.assertIn("商业银行应当保护存款人的合法权益。[1]", answer)
        self.assertEqual(confidence, "medium")

    def test_generation_routes_by_mode(self):
        state = {"question": "test", "documents": []}
        with patch.object(retrieval, "generate_fast_answer", return_value=("fast", "low")) as fast:
            with patch.object(retrieval, "generate_answer", return_value=("smart", "high")) as smart:
                self.assertEqual(retrieval._generate({**state, "mode": "fast"})["answer"], "fast")
                self.assertEqual(retrieval._generate({**state, "mode": "smart"})["answer"], "smart")
        fast.assert_called_once()
        smart.assert_called_once()


if __name__ == "__main__":
    unittest.main()

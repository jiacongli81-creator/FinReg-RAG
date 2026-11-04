"""Check that standalone search ranks source chunks without invoking question answering."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.search import search_keywords


def row(chunk_id: str, content: str, title: str = "测试制度") -> dict:
    return {
        "id": chunk_id, "document_id": "doc-1", "title": title,
        "content": content, "page": 2, "section": "第二章",
        "effective_date": None, "validity": "valid",
    }


class KeywordSearchTests(unittest.TestCase):
    def test_matches_and_returns_source_metadata(self):
        chunks = [row("hit", "存款保险保障存款人权益。"), row("miss", "证券市场交易规则。")]
        with patch("app.services.search.get_search_chunks", return_value=chunks) as get_chunks:
            results = search_keywords("存款保险", limit=10, only_valid=True)
        get_chunks.assert_called_once_with(True)
        self.assertEqual([item["chunk_id"] for item in results], ["hit"])
        self.assertEqual(results[0]["page"], 2)
        self.assertEqual(results[0]["document_id"], "doc-1")
        self.assertGreater(results[0]["score"], 0)

    def test_api_uses_keyword_search_only(self):
        client = TestClient(app)
        with patch("app.main.search_keywords", return_value=[{
            "document_id": "doc-1", "title": "测试制度", "chunk_id": "hit",
            "page": 2, "section": None, "score": 1.5, "content": "存款保险",
            "effective_date": None, "validity": "valid",
        }]) as search:
            with patch("app.main.query", side_effect=AssertionError("Question answering was called")):
                response = client.get("/search", params={"query": " 存款保险 ", "limit": 10,
                                                          "only_valid": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["query"], "存款保险")
        self.assertEqual(response.json()["results"][0]["chunk_id"], "hit")
        search.assert_called_once_with("存款保险", limit=10, only_valid=False)

    def test_rejects_blank_and_invalid_limit(self):
        client = TestClient(app)
        self.assertEqual(client.get("/search", params={"query": "   "}).status_code, 422)
        self.assertEqual(client.get("/search", params={"query": "存款", "limit": 0}).status_code, 422)


if __name__ == "__main__":
    unittest.main()

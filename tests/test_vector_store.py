"""Startup reconciliation must not duplicate vectors already stored in Milvus."""

import json
import unittest
from unittest.mock import MagicMock, patch

from app.services.vector_store import sync_existing_vectors


class VectorStoreSyncTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"id": "existing", "document_id": "doc", "embedding": json.dumps([1.0, 0.0]),
             "validity": "valid"},
            {"id": "missing", "document_id": "doc", "embedding": json.dumps([0.0, 1.0]),
             "validity": "unknown"},
        ]

    def test_startup_sync_only_adds_missing_vectors(self):
        client = MagicMock()
        client.has_collection.return_value = True
        client.get.return_value = [{"id": "existing"}]
        with patch("app.db.get_chunks", return_value=self.rows), \
             patch("app.services.vector_store._client", return_value=client), \
             patch("app.services.vector_store.upsert_vectors") as upsert:
            count = sync_existing_vectors()
        self.assertEqual(count, 1)
        self.assertEqual([item["id"] for item in upsert.call_args.args[0]], ["missing"])

    def test_force_sync_replaces_all_vectors(self):
        client = MagicMock()
        with patch("app.db.get_chunks", return_value=self.rows), \
             patch("app.services.vector_store._client", return_value=client), \
             patch("app.services.vector_store.upsert_vectors") as upsert:
            count = sync_existing_vectors(force=True)
        self.assertEqual(count, 2)
        self.assertEqual(len(upsert.call_args.args[0]), 2)
        client.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()

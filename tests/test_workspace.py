"""Workspace persistence and safe update scanning on an isolated SQLite corpus."""

import tempfile
import unittest
import sqlite3
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app import workspace_store as store
from app.config import settings
from app.services import updates


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.raw = root / "raw"
        self.converted = root / "converted"
        self.raw.mkdir()
        self.converted.mkdir()
        isolated = replace(settings, database_backend="sqlite", database_path=root / "workspace.db",
                           raw_data_dir=self.raw, converted_data_dir=self.converted)
        @contextmanager
        def connect():
            connection = sqlite3.connect(isolated.database_path)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()

        self.connect = connect
        def list_documents():
            with connect() as connection:
                return connection.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()

        self.patches = [patch("app.workspace_store.settings", isolated),
                        patch("app.workspace_store.connect", connect),
                        patch("app.services.updates.settings", isolated),
                        patch("app.services.updates.list_documents", list_documents)]
        for item in self.patches:
            item.start()
        with connect() as connection:
            connection.executescript("""CREATE TABLE documents (
                id TEXT PRIMARY KEY, title TEXT, filename TEXT, file_type TEXT,
                effective_date TEXT, validity TEXT, created_at TEXT, status TEXT, error TEXT);
                CREATE TABLE qa_history (id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT, answer TEXT, sources TEXT, created_at TEXT);""")
        store.init_workspace_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def document(self, name="existing.txt", document_id="doc-1"):
        with self.connect() as connection:
            connection.execute("""INSERT INTO documents
                (id, title, filename, file_type, effective_date, validity, created_at, status, error)
                VALUES (?, ?, ?, 'txt', NULL, 'unknown', ?, 'ready', NULL)""",
                (document_id, Path(name).stem, name, store.utc_now()))

    def test_history_favorite_snapshot_and_tags(self):
        with self.connect() as connection:
            cursor = connection.execute("""INSERT INTO qa_history (question, answer, sources, created_at)
                VALUES (?, ?, ?, ?)""", ("测试问题", "测试回答",
                                      json.dumps([{"title": "依据"}]), store.utc_now()))
            history_id = cursor.lastrowid
        self.assertEqual(store.list_history("测试问题")[0]["id"], history_id)
        favorite = store.add_favorite(history_id)
        self.assertEqual(store.add_favorite(history_id)["id"], favorite["id"])
        self.assertTrue(store.delete_history(history_id))
        self.assertEqual(store.list_favorites("测试回答")[0]["sources"][0]["title"], "依据")
        self.assertIsNone(store.list_favorites()[0]["history_id"])
        self.assertTrue(store.delete_favorite(favorite["id"]))

        self.document()
        tag = store.add_tag("原标签")
        self.assertEqual(store.set_document_tags("doc-1", [tag["id"]])[0]["name"], "原标签")
        self.assertEqual(store.list_tags()[0]["document_count"], 1)
        self.assertTrue(store.rename_tag(tag["id"], "新标签"))
        self.assertEqual(store.get_document_tags("doc-1")[0]["name"], "新标签")
        self.assertTrue(store.delete_tag(tag["id"]))
        self.assertEqual(store.get_document_tags("doc-1"), [])

    def test_update_baseline_add_change_skip_and_failure(self):
        self.document()
        (self.raw / "existing.txt").write_text("原资料", encoding="utf-8")
        new_file = self.raw / "new.txt"
        new_file.write_text("新资料", encoding="utf-8")
        tag = store.add_tag("资料标签")

        def ingest(path):
            if path.read_text(encoding="utf-8") == "错误资料":
                raise ValueError("无法解析")
            with self.connect() as connection:
                count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            document_id = f"doc-{count + 1}"
            self.document(path.name, document_id)
            return {"id": document_id}

        with patch("app.services.updates.ingest_file", side_effect=ingest) as importer:
            first = updates.scan_updates()
            self.assertEqual((first["added"], first["skipped"], first["failed"]), (1, 1, 0))
            self.assertEqual(importer.call_count, 1)
            self.assertIn("baseline", [item["status"] for item in first["details"]])

            second = updates.scan_updates()
            self.assertEqual((second["skipped"], second["added"]), (2, 0))
            store.set_document_tags("doc-2", [tag["id"]])
            new_file.write_text("修改资料", encoding="utf-8")
            third = updates.scan_updates()
            self.assertEqual(third["updated"], 1)
            self.assertEqual(store.get_document_tags("doc-2"), [])
            self.assertEqual(store.get_document_tags("doc-3")[0]["id"], tag["id"])
            with self.connect() as conn:
                self.assertEqual(conn.execute("SELECT validity FROM documents WHERE id='doc-2'").fetchone()[0],
                                 "invalid")

            new_file.write_text("错误资料", encoding="utf-8")
            failed = updates.scan_updates()
            self.assertEqual(failed["failed"], 1)
            self.assertEqual(store.get_source_file("raw/new.txt")["document_id"], "doc-3")

    def test_ambiguous_baseline_does_not_import_or_claim_source(self):
        self.document("same.txt")
        (self.raw / "same.txt").write_text("第一份", encoding="utf-8")
        (self.converted / "same.txt").write_text("第二份", encoding="utf-8")
        with patch("app.services.updates.ingest_file") as importer:
            run = updates.scan_updates()
        self.assertEqual(run["failed"], 2)
        importer.assert_not_called()
        self.assertIsNone(store.get_source_file("raw/same.txt"))


if __name__ == "__main__":
    unittest.main()

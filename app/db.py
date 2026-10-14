import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                effective_date TEXT,
                validity TEXT NOT NULL DEFAULT 'unknown',
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id),
                content TEXT NOT NULL,
                page INTEGER,
                section TEXT,
                embedding TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS qa_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
            """
        )


def insert_document(document: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO documents
            (id, title, filename, file_type, effective_date, validity, created_at, status, error)
            VALUES (:id, :title, :filename, :file_type, :effective_date, :validity,
                    :created_at, :status, :error)""",
            document,
        )


def insert_chunks(chunks: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.executemany(
            """INSERT INTO chunks (id, document_id, content, page, section, embedding)
            VALUES (:id, :document_id, :content, :page, :section, :embedding)""",
            [{**c, "embedding": json.dumps(c["embedding"], ensure_ascii=False)} for c in chunks],
        )


def list_documents() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            """SELECT d.*, COUNT(c.id) AS chunk_count
               FROM documents d
               LEFT JOIN chunks c ON c.document_id = d.id
               GROUP BY d.id
               ORDER BY d.created_at DESC"""
        ).fetchall()


def get_chunks(only_valid: bool) -> list[sqlite3.Row]:
    sql = """SELECT c.*, d.title, d.filename, d.effective_date, d.validity
             FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE d.status = 'ready'"""
    params: tuple[Any, ...] = ()
    if only_valid:
        sql += " AND d.validity IN ('valid', 'unknown')"
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def save_history(question: str, answer: str, sources: list[dict[str, Any]]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO qa_history (question, answer, sources, created_at) VALUES (?, ?, ?, ?)",
            (question, answer, json.dumps(sources, ensure_ascii=False), utc_now()),
        )

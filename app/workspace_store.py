"""Small user workspace tables shared by SQLite and MySQL deployments."""

import hashlib
import json
import uuid

from .config import settings
from .db import connect, utc_now


def _mysql() -> bool:
    return settings.database_backend == "mysql"


def _sql(sql: str) -> str:
    return sql.replace("?", "%s") if _mysql() else sql


def _rows(cursor) -> list[dict]:
    return [dict(row) if hasattr(row, "keys") else dict(zip(cursor.column_names, row))
            for row in cursor.fetchall()]


def _execute(sql: str, params: tuple = (), *, fetch: bool = True) -> list[dict]:
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql(sql), params)
            return _rows(cursor) if fetch else []
        finally:
            cursor.close()


def init_workspace_db() -> None:
    if _mysql():
        statements = [
            """CREATE TABLE IF NOT EXISTS favorites (id VARCHAR(36) PRIMARY KEY,
               history_id BIGINT UNIQUE, question TEXT NOT NULL, answer LONGTEXT NOT NULL,
               sources LONGTEXT NOT NULL, created_at VARCHAR(64) NOT NULL,
               INDEX idx_favorites_created (created_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS tags (id VARCHAR(36) PRIMARY KEY,
               name VARCHAR(100) NOT NULL UNIQUE, created_at VARCHAR(64) NOT NULL)
               ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS document_tags (document_id VARCHAR(36) NOT NULL,
               tag_id VARCHAR(36) NOT NULL, PRIMARY KEY (document_id, tag_id),
               FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
               FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE)
               ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS source_files (path_hash CHAR(64) PRIMARY KEY,
               path TEXT NOT NULL, content_sha256 CHAR(64) NOT NULL,
               document_id VARCHAR(36), observed_at VARCHAR(64) NOT NULL)
               ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS update_runs (id VARCHAR(36) PRIMARY KEY,
               created_at VARCHAR(64) NOT NULL, added INT NOT NULL,
               updated INT NOT NULL, skipped INT NOT NULL, failed INT NOT NULL,
               details LONGTEXT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        ]
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS favorites (id TEXT PRIMARY KEY,
               history_id INTEGER UNIQUE, question TEXT NOT NULL, answer TEXT NOT NULL,
               sources TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS tags (id TEXT PRIMARY KEY,
               name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS document_tags (document_id TEXT NOT NULL,
               tag_id TEXT NOT NULL, PRIMARY KEY (document_id, tag_id))""",
            """CREATE TABLE IF NOT EXISTS source_files (path_hash TEXT PRIMARY KEY,
               path TEXT NOT NULL, content_sha256 TEXT NOT NULL,
               document_id TEXT, observed_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS update_runs (id TEXT PRIMARY KEY,
               created_at TEXT NOT NULL, added INTEGER NOT NULL,
               updated INTEGER NOT NULL, skipped INTEGER NOT NULL, failed INTEGER NOT NULL,
               details TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_favorites_created ON favorites(created_at)",
        ]
    with connect() as conn:
        cursor = conn.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
        finally:
            cursor.close()


def list_history(term: str = "", limit: int = 100) -> list[dict]:
    rows = _execute("""SELECT id, question, answer, sources, created_at FROM qa_history
        WHERE (? = '' OR question LIKE ? OR answer LIKE ?)
        ORDER BY id DESC LIMIT ?""", (term, f"%{term}%", f"%{term}%", limit))
    for row in rows:
        row["sources"] = json.loads(row["sources"])
    return rows


def get_history(history_id: int) -> dict | None:
    rows = _execute("SELECT id, question, answer, sources, created_at FROM qa_history WHERE id=?",
                    (history_id,))
    if rows:
        rows[0]["sources"] = json.loads(rows[0]["sources"])
        return rows[0]
    return None


def delete_history(history_id: int) -> bool:
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql("UPDATE favorites SET history_id=NULL WHERE history_id=?"), (history_id,))
            cursor.execute(_sql("DELETE FROM qa_history WHERE id=?"), (history_id,))
            return cursor.rowcount > 0
        finally:
            cursor.close()


def list_favorites(term: str = "") -> list[dict]:
    rows = _execute("""SELECT id, history_id, question, answer, sources, created_at FROM favorites
        WHERE (? = '' OR question LIKE ? OR answer LIKE ?) ORDER BY created_at DESC""",
        (term, f"%{term}%", f"%{term}%"))
    for row in rows:
        row["sources"] = json.loads(row["sources"])
    return rows


def add_favorite(history_id: int) -> dict | None:
    row = get_history(history_id)
    if row is None:
        return None
    existing = _execute("SELECT id FROM favorites WHERE history_id=?", (history_id,))
    if existing:
        return next(item for item in list_favorites() if item["id"] == existing[0]["id"])
    favorite_id = str(uuid.uuid4())
    _execute("""INSERT INTO favorites (id, history_id, question, answer, sources, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (favorite_id, history_id, row["question"], row["answer"],
         json.dumps(row["sources"], ensure_ascii=False), utc_now()), fetch=False)
    return next(item for item in list_favorites() if item["id"] == favorite_id)


def delete_favorite(favorite_id: str) -> bool:
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql("DELETE FROM favorites WHERE id=?"), (favorite_id,))
            return cursor.rowcount > 0
        finally:
            cursor.close()


def list_tags() -> list[dict]:
    return _execute("""SELECT t.id, t.name, t.created_at, COUNT(dt.document_id) AS document_count
        FROM tags t LEFT JOIN document_tags dt ON dt.tag_id=t.id
        GROUP BY t.id, t.name, t.created_at ORDER BY t.name""")


def add_tag(name: str) -> dict:
    existing = _execute("SELECT id FROM tags WHERE name=?", (name,))
    if existing:
        raise ValueError("标签已存在")
    tag_id = str(uuid.uuid4())
    _execute("INSERT INTO tags (id, name, created_at) VALUES (?, ?, ?)",
             (tag_id, name, utc_now()), fetch=False)
    return next(tag for tag in list_tags() if tag["id"] == tag_id)


def rename_tag(tag_id: str, name: str) -> bool:
    if _execute("SELECT id FROM tags WHERE name=? AND id<>?", (name, tag_id)):
        raise ValueError("标签已存在")
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql("UPDATE tags SET name=? WHERE id=?"), (name, tag_id))
            return cursor.rowcount > 0
        finally:
            cursor.close()


def delete_tag(tag_id: str) -> bool:
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql("DELETE FROM document_tags WHERE tag_id=?"), (tag_id,))
            cursor.execute(_sql("DELETE FROM tags WHERE id=?"), (tag_id,))
            return cursor.rowcount > 0
        finally:
            cursor.close()


def get_document_tags(document_id: str) -> list[dict]:
    return _execute("""SELECT t.id, t.name FROM tags t JOIN document_tags dt ON dt.tag_id=t.id
        WHERE dt.document_id=? ORDER BY t.name""", (document_id,))


def set_document_tags(document_id: str, tag_ids: list[str]) -> list[dict]:
    if not _execute("SELECT id FROM documents WHERE id=?", (document_id,)):
        raise LookupError("没有找到文档")
    if tag_ids:
        found = _execute("SELECT id FROM tags WHERE id IN (" + ",".join("?" for _ in tag_ids) + ")",
                         tuple(tag_ids))
        if len(found) != len(set(tag_ids)):
            raise ValueError("包含不存在的标签")
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql("DELETE FROM document_tags WHERE document_id=?"), (document_id,))
            for tag_id in set(tag_ids):
                cursor.execute(_sql("INSERT INTO document_tags (document_id, tag_id) VALUES (?, ?)"),
                               (document_id, tag_id))
        finally:
            cursor.close()
    return get_document_tags(document_id)


def get_source_file(path: str) -> dict | None:
    rows = _execute("SELECT path, content_sha256, document_id FROM source_files WHERE path_hash=?",
                    (hashlib.sha256(path.encode()).hexdigest(),))
    return rows[0] if rows else None


def record_source_file(path: str, digest: str, document_id: str | None) -> None:
    path_hash = hashlib.sha256(path.encode()).hexdigest()
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(_sql("DELETE FROM source_files WHERE path_hash=?"), (path_hash,))
            cursor.execute(_sql("""INSERT INTO source_files
                (path_hash, path, content_sha256, document_id, observed_at)
                VALUES (?, ?, ?, ?, ?)"""), (path_hash, path, digest, document_id, utc_now()))
        finally:
            cursor.close()


def invalidate_document(document_id: str) -> None:
    _execute("UPDATE documents SET validity='invalid' WHERE id=?", (document_id,), fetch=False)


def finalize_import(path: str, digest: str, document_id: str,
                    previous_document_id: str | None = None) -> None:
    """Publish a new source version and carry its tags forward atomically."""
    path_hash = hashlib.sha256(path.encode()).hexdigest()
    with connect() as conn:
        cursor = conn.cursor()
        try:
            if previous_document_id and previous_document_id != document_id:
                cursor.execute(_sql("SELECT tag_id FROM document_tags WHERE document_id=?"),
                               (previous_document_id,))
                tag_ids = [row[0] for row in cursor.fetchall()]
                for tag_id in tag_ids:
                    cursor.execute(_sql("INSERT INTO document_tags (document_id, tag_id) VALUES (?, ?)"),
                                   (document_id, tag_id))
                cursor.execute(_sql("DELETE FROM document_tags WHERE document_id=?"),
                               (previous_document_id,))
                cursor.execute(_sql("UPDATE documents SET validity='invalid' WHERE id=?"),
                               (previous_document_id,))
            cursor.execute(_sql("DELETE FROM source_files WHERE path_hash=?"), (path_hash,))
            cursor.execute(_sql("""INSERT INTO source_files
                (path_hash, path, content_sha256, document_id, observed_at)
                VALUES (?, ?, ?, ?, ?)"""), (path_hash, path, digest, document_id, utc_now()))
        finally:
            cursor.close()


def create_update_run(counts: dict, details: list[dict]) -> dict:
    run = {"id": str(uuid.uuid4()), "created_at": utc_now(), **counts, "details": details}
    _execute("""INSERT INTO update_runs (id, created_at, added, updated, skipped, failed, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run["id"], run["created_at"], run["added"], run["updated"],
         run["skipped"], run["failed"], json.dumps(details, ensure_ascii=False)), fetch=False)
    return run


def list_update_runs(limit: int = 20) -> list[dict]:
    rows = _execute("""SELECT id, created_at, added, updated, skipped, failed, details
        FROM update_runs ORDER BY created_at DESC LIMIT ?""", (limit,))
    for row in rows:
        row["details"] = json.loads(row["details"])
    return rows

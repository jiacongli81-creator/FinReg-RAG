"""Rebuild stored chunk vectors using the configured Ollama embedding model."""

from __future__ import annotations

import json
import sqlite3
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.db import get_ready_chunks_for_embedding, update_chunk_embeddings


def main() -> int:
    if settings.embedding_provider != "ollama":
        print("Set EMBEDDING_PROVIDER=ollama before rebuilding.", file=sys.stderr)
        return 2

    rows = get_ready_chunks_for_embedding()
    if not rows:
        print("No ready chunks found.")
        return 0

    vectors: dict[str, list[float]] = {}
    batch_size = 32
    url = settings.embedding_base_url.rstrip("/") + "/api/embed"
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        payload = json.dumps(
            {"model": settings.embedding_model, "input": [row["content"] for row in batch]}
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.embedding_timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Embedding batch failed; database was not changed: {exc}", file=sys.stderr)
            return 1

        batch_vectors = result.get("embeddings", [])
        if len(batch_vectors) != len(batch) or any(not vector for vector in batch_vectors):
            print("Ollama returned an incomplete batch; database was not changed.", file=sys.stderr)
            return 1
        vectors.update((row["id"], vector) for row, vector in zip(batch, batch_vectors))
        print(f"Embedded {min(start + len(batch), len(rows))}/{len(rows)} chunks")

    dimensions = {len(vector) for vector in vectors.values()}
    if len(vectors) != len(rows) or len(dimensions) != 1:
        print("Vector count or dimensions are inconsistent; database was not changed.", file=sys.stderr)
        return 1

    database = settings.database_path
    backup_dir = database.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{database.stem}-before-ollama-{datetime.now():%Y%m%d-%H%M%S}{database.suffix}"
    with sqlite3.connect(database) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    update_chunk_embeddings(vectors)
    print(f"Updated {len(vectors)} vectors ({next(iter(dimensions))} dimensions).")
    print(f"Database backup: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

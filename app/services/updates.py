"""Scan the local corpus and import new or changed files without reimporting the baseline."""

import hashlib
import threading
from collections import Counter
from pathlib import Path

from ..config import settings
from ..db import list_documents
from ..workspace_store import (create_update_run, finalize_import, get_source_file,
                               record_source_file)
from .ingestion import SUPPORTED, ingest_file


_scan_lock = threading.Lock()


def source_key(path: Path) -> str:
    """Use the same stable data-relative key for uploads and directory scans."""
    return path.relative_to(settings.raw_data_dir.parent).as_posix()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_updates() -> dict:
    if not _scan_lock.acquire(blocking=False):
        raise RuntimeError("已有更新任务正在运行")
    try:
        latest_by_name = {}
        for document in list_documents():
            row = dict(document) if hasattr(document, "keys") else document
            if row["status"] == "ready":
                latest_by_name.setdefault(row["filename"], row)
        counts = {"added": 0, "updated": 0, "skipped": 0, "failed": 0}
        details = []
        paths = sorted({path for directory in (settings.raw_data_dir, settings.converted_data_dir)
                        for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED})
        filename_counts = Counter(path.name for path in paths)
        for path in paths:
            relative = source_key(path)
            try:
                digest = file_digest(path)
                previous = get_source_file(relative)
                if previous and previous["content_sha256"] == digest:
                    counts["skipped"] += 1
                    continue
                if previous is None and filename_counts[path.name] > 1 and path.name in latest_by_name:
                    counts["failed"] += 1
                    details.append({"path": relative, "status": "failed",
                                    "error": "多个资料目录存在同名文件，无法确认已导入版本；请先重命名区分"})
                    continue
                # Existing databases predate source tracking. Only infer a baseline when
                # a filename identifies exactly one file in the scanned directories.
                if previous is None and filename_counts[path.name] == 1 and path.name in latest_by_name:
                    row = latest_by_name[path.name]
                    record_source_file(relative, digest, row["id"])
                    counts["skipped"] += 1
                    details.append({"path": relative, "status": "baseline", "document_id": row["id"]})
                    continue
                document = ingest_file(path)
                if previous and previous["document_id"]:
                    outcome = "updated"
                else:
                    outcome = "added"
                finalize_import(relative, digest, document["id"],
                                previous["document_id"] if previous else None)
                counts[outcome] += 1
                details.append({"path": relative, "status": outcome, "document_id": document["id"]})
            except Exception as exc:
                counts["failed"] += 1
                details.append({"path": relative, "status": "failed", "error": str(exc)})
        return create_update_run(counts, details)
    finally:
        _scan_lock.release()

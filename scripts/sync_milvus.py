"""Reconcile existing ready MySQL chunks with the Milvus vector collection."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.vector_store import sync_existing_vectors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace stored vectors after re-embedding")
    args = parser.parse_args()
    if settings.vector_backend != "milvus":
        raise SystemExit("Set VECTOR_BACKEND=milvus before syncing vectors")
    print(f"Synced {sync_existing_vectors(force=args.force)} ready chunk vectors to Milvus")

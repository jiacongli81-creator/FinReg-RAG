"""Milvus Standalone adapter for chunk vectors.

MySQL remains the source of truth for chunk text and document metadata. Its
stored vectors also allow the existing evaluation scripts to run unchanged.
"""

import json
from functools import lru_cache

from ..config import settings


@lru_cache(maxsize=1)
def _client():
    from pymilvus import MilvusClient

    return MilvusClient(uri=settings.milvus_uri)


def _ensure_collection(dimension: int) -> None:
    from pymilvus import DataType

    client = _client()
    name = settings.milvus_collection
    if client.has_collection(name):
        description = client.describe_collection(name)
        fields = {field["name"]: field for field in description["fields"]}
        configured_dimension = int(fields["vector"]["params"]["dim"])
        if configured_dimension != dimension:
            raise RuntimeError(
                f"Milvus 集合维度 {configured_dimension} 与当前 embedding 维度 {dimension} 不同；"
                "请核对模型及迁移方案"
            )
        return

    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=36)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dimension)
    schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=36)
    schema.add_field(field_name="validity", datatype=DataType.VARCHAR, max_length=32)
    indexes = client.prepare_index_params()
    indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(collection_name=name, schema=schema, index_params=indexes)


def upsert_vectors(chunks: list[dict]) -> None:
    if not chunks:
        return
    _ensure_collection(len(chunks[0]["embedding"]))
    data = [
        {"id": chunk["id"], "vector": chunk["embedding"],
         "document_id": chunk["document_id"], "validity": chunk.get("validity", "unknown")}
        for chunk in chunks
    ]
    for start in range(0, len(data), 128):
        _client().upsert(collection_name=settings.milvus_collection, data=data[start:start + 128])


def search_vectors(vector: list[float], limit: int, only_valid: bool) -> list[tuple[str, float]]:
    _ensure_collection(len(vector))
    results = _client().search(
        collection_name=settings.milvus_collection,
        data=[vector], limit=limit,
        filter='validity != "invalid"' if only_valid else "",
        search_params={"metric_type": "COSINE"},
    )
    return [(str(hit["id"]), float(hit["distance"])) for hit in results[0]]


def sync_existing_vectors(*, force: bool = False) -> int:
    """Add missing MySQL vectors, or explicitly replace all vectors after re-embedding."""
    from ..db import get_chunks

    rows = get_chunks(False)
    synced = 0
    for start in range(0, len(rows), 128):
        selected = rows[start:start + 128]
        if not force:
            existing = _client().get(
                collection_name=settings.milvus_collection,
                ids=[row["id"] for row in selected],
                output_fields=["id"],
            ) if _client().has_collection(settings.milvus_collection) else []
            existing_ids = {item["id"] for item in existing}
            selected = [row for row in selected if row["id"] not in existing_ids]
        batch = [
            {"id": row["id"], "document_id": row["document_id"],
             "embedding": json.loads(row["embedding"]), "validity": row["validity"]}
            for row in selected
        ]
        upsert_vectors(batch)
        synced += len(batch)
    return synced

import time
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response

from .config import settings
from .db import get_document_chunks, init_db, list_documents
from .law_library import get_article, init_law_db, list_laws, search_articles
from .schemas import (
    DirectoryIngestResponse,
    DocumentContentResponse,
    DocumentResponse,
    QueryRequest,
    QueryResponse,
    KeywordSearchResponse,
    FavoriteRequest,
    TagRequest,
    DocumentTagsRequest,
)
from .services.ingestion import SUPPORTED, ingest_file
from .services.mineru_parser import mineru_status
from .services.retrieval import query, warm_fast_retrieval
from .services.search import search_keywords
from .services.vector_store import sync_existing_vectors
from .services.updates import scan_updates, source_key
from .workspace_store import (init_workspace_db, list_history, get_history, delete_history,
                              list_favorites, add_favorite, delete_favorite, list_tags,
                              add_tag, rename_tag, delete_tag, get_document_tags,
                              set_document_tags, list_update_runs, get_source_file,
                              finalize_import)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    init_law_db()
    init_workspace_db()
    if settings.vector_backend == "milvus":
        sync_existing_vectors()
    warm_fast_retrieval()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/test", include_in_schema=False, response_class=HTMLResponse)
def test_page() -> HTMLResponse:
    page = (Path(__file__).parent / "test.html").read_text(encoding="utf-8")
    return HTMLResponse(page)


@app.get("/workspace.js", include_in_schema=False)
def workspace_script() -> Response:
    return Response((Path(__file__).parent / "workspace.js").read_text(encoding="utf-8"),
                    media_type="application/javascript")


@app.get("/legacy-test", include_in_schema=False, response_class=HTMLResponse)
def legacy_test_page() -> HTMLResponse:
    page = (Path(__file__).parent / "legacy_test.html").read_text(encoding="utf-8")
    return HTMLResponse(page)


@app.get("/laws-ui", include_in_schema=False, response_class=HTMLResponse)
def laws_page() -> HTMLResponse:
    return HTMLResponse((Path(__file__).parent / "laws.html").read_text(encoding="utf-8"))


@app.get("/laws")
def laws() -> list[dict]:
    return list_laws()


@app.get("/laws/articles")
def law_articles(query: str = "", law_id: str | None = None, limit: int = 30, offset: int = 0) -> list[dict]:
    try:
        return search_articles(query, law_id, limit, offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/laws/articles/{article_id}")
def law_article(article_id: str) -> dict:
    article = get_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="没有找到这条法规条文")
    return article


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "database": str(settings.database_path) if settings.database_backend == "sqlite" else f"mysql://{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}",
        "database_backend": settings.database_backend,
        "llm_provider": settings.llm_provider,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "vector_backend": settings.vector_backend,
        "rag_orchestrator": "langchain",
        "mineru": mineru_status(),
    }


@app.get("/search", response_model=KeywordSearchResponse)
def keyword_search(query: str = Query(min_length=1, max_length=200),
                   limit: int = Query(default=20, ge=1, le=100),
                   only_valid: bool = True) -> KeywordSearchResponse:
    term = query.strip()
    if not term:
        raise HTTPException(status_code=422, detail="请输入关键词")
    started = time.perf_counter()
    results = search_keywords(term, limit=limit, only_valid=only_valid)
    return KeywordSearchResponse(query=term, results=results,
                                 elapsed_ms=round((time.perf_counter() - started) * 1000))


def _response(row) -> DocumentResponse:
    data = dict(row) if hasattr(row, "keys") else row
    return DocumentResponse(**data)


@app.get("/documents", response_model=list[DocumentResponse])
def documents() -> list[DocumentResponse]:
    return [_response(row) for row in list_documents()]


@app.get("/documents/{document_id}/content", response_model=DocumentContentResponse)
def document_content(document_id: str) -> DocumentContentResponse:
    chunks = [dict(row) for row in get_document_chunks(document_id)]
    if not chunks:
        raise HTTPException(status_code=404, detail="没有找到该文档的识别内容")
    return DocumentContentResponse(document_id=document_id, chunks=chunks)


@app.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix}")
    target = settings.raw_data_dir / filename
    content = await file.read()
    target.write_bytes(content)
    try:
        document = ingest_file(target)
        key = source_key(target)
        previous = get_source_file(key)
        finalize_import(key, hashlib.sha256(content).hexdigest(), document["id"],
                        previous["document_id"] if previous else None)
        return DocumentResponse(**document)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/documents/ingest-directory", response_model=DirectoryIngestResponse)
def ingest_directory() -> DirectoryIngestResponse:
    input_dirs = [settings.raw_data_dir, settings.converted_data_dir]
    files = [path for directory in input_dirs for path in directory.rglob("*") if path.is_file()]
    results = []
    errors = []
    for path in files:
        try:
            results.append(DocumentResponse(**ingest_file(path)))
        except Exception as exc:
            errors.append({"filename": path.name, "error": str(exc)})
    return DirectoryIngestResponse(processed=len(files), succeeded=len(results), failed=len(errors), documents=results, errors=errors)


@app.post("/query", response_model=QueryResponse)
def ask(request: QueryRequest) -> QueryResponse:
    started = time.perf_counter()
    try:
        answer, confidence, sources, history_id = query(request.question, request.top_k, request.only_valid, request.mode)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    provider = "local_extractive" if request.mode == "fast" else settings.llm_provider
    return QueryResponse(answer=answer, confidence=confidence, sources=sources, elapsed_ms=elapsed_ms,
                         llm_provider=provider, mode=request.mode, history_id=history_id)


@app.get("/history")
def history(query: str = "", limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return list_history(query.strip(), limit)


@app.get("/history/{history_id}")
def history_item(history_id: int) -> dict:
    item = get_history(history_id)
    if item is None:
        raise HTTPException(status_code=404, detail="没有找到这条问答记录")
    return item


@app.delete("/history/{history_id}")
def remove_history(history_id: int) -> dict:
    if not delete_history(history_id):
        raise HTTPException(status_code=404, detail="没有找到这条问答记录")
    return {"deleted": True}


@app.get("/favorites")
def favorites(query: str = "") -> list[dict]:
    return list_favorites(query.strip())


@app.post("/favorites")
def favorite(request: FavoriteRequest) -> dict:
    item = add_favorite(request.history_id)
    if item is None:
        raise HTTPException(status_code=404, detail="没有找到这条问答记录")
    return item


@app.delete("/favorites/{favorite_id}")
def remove_favorite(favorite_id: str) -> dict:
    if not delete_favorite(favorite_id):
        raise HTTPException(status_code=404, detail="没有找到这条收藏")
    return {"deleted": True}


@app.get("/tags")
def tags() -> list[dict]:
    return list_tags()


@app.post("/tags")
def create_tag(request: TagRequest) -> dict:
    try:
        name = request.name.strip()
        if not name:
            raise ValueError("请输入标签名称")
        return add_tag(name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/tags/{tag_id}")
def update_tag(tag_id: str, request: TagRequest) -> dict:
    try:
        name = request.name.strip()
        if not name:
            raise ValueError("请输入标签名称")
        changed = rename_tag(tag_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(status_code=404, detail="没有找到该标签")
    return next(tag for tag in list_tags() if tag["id"] == tag_id)


@app.delete("/tags/{tag_id}")
def remove_tag(tag_id: str) -> dict:
    if not delete_tag(tag_id):
        raise HTTPException(status_code=404, detail="没有找到该标签")
    return {"deleted": True}


@app.get("/documents/{document_id}/tags")
def document_tags(document_id: str) -> list[dict]:
    return get_document_tags(document_id)


@app.put("/documents/{document_id}/tags")
def update_document_tags(document_id: str, request: DocumentTagsRequest) -> list[dict]:
    try:
        return set_document_tags(document_id, request.tag_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/updates")
def updates() -> list[dict]:
    return list_update_runs()


@app.post("/updates/scan")
def run_update_scan() -> dict:
    try:
        return scan_updates()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

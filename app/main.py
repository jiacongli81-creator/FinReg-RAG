import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from .config import settings
from .db import init_db, list_documents
from .schemas import DirectoryIngestResponse, DocumentResponse, QueryRequest, QueryResponse
from .services.ingestion import SUPPORTED, ingest_file
from .services.retrieval import query


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/test", include_in_schema=False, response_class=HTMLResponse)
def test_page() -> HTMLResponse:
    page = (Path(__file__).parent / "test.html").read_text(encoding="utf-8")
    return HTMLResponse(page)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "database": str(settings.database_path), "llm_provider": settings.llm_provider}


def _response(row) -> DocumentResponse:
    data = dict(row) if hasattr(row, "keys") else row
    return DocumentResponse(**data)


@app.get("/documents", response_model=list[DocumentResponse])
def documents() -> list[DocumentResponse]:
    return [_response(row) for row in list_documents()]


@app.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(file: UploadFile = File(...)) -> DocumentResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix}")
    target = settings.raw_data_dir / (file.filename or "upload" + suffix)
    target.write_bytes(await file.read())
    try:
        return DocumentResponse(**ingest_file(target))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/documents/ingest-directory", response_model=DirectoryIngestResponse)
def ingest_directory() -> DirectoryIngestResponse:
    files = [path for path in settings.raw_data_dir.rglob("*") if path.is_file()]
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
        answer, confidence, sources = query(request.question, request.top_k, request.only_valid)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return QueryResponse(answer=answer, confidence=confidence, sources=sources, elapsed_ms=elapsed_ms, llm_provider=settings.llm_provider)

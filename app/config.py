from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Financial Regulation RAG API")
    database_path: Path = ROOT_DIR / os.getenv("DATABASE_PATH", "data/app.db")
    raw_data_dir: Path = ROOT_DIR / os.getenv("RAW_DATA_DIR", "data/raw")
    converted_data_dir: Path = ROOT_DIR / os.getenv("CONVERTED_DATA_DIR", "data/converted")
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "120"))
    retrieval_top_k: int = int(os.getenv("RETRIEVAL_TOP_K", "5"))
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "ollama")
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:11434")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "shaw/dmeta-embedding-zh:latest")
    embedding_timeout_seconds: int = int(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120"))
    mineru_enabled: bool = os.getenv("MINERU_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    mineru_python: Path = Path(os.getenv("MINERU_PYTHON", str(ROOT_DIR / "mineru_runtime" / ".venv" / "Scripts" / "python.exe")))
    mineru_home: Path = Path(os.getenv("MINERU_HOME", str(ROOT_DIR / "mineru_runtime" / ".mineru")))
    mineru_temp_dir: Path = Path(os.getenv("MINERU_TEMP_DIR", str(ROOT_DIR / "mineru_runtime" / "tmp")))
    mineru_output_dir: Path = Path(os.getenv("MINERU_OUTPUT_DIR", str(ROOT_DIR / "mineru_runtime" / "project-output")))
    mineru_timeout_seconds: int = int(os.getenv("MINERU_TIMEOUT_SECONDS", "1800"))


settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
settings.converted_data_dir.mkdir(parents=True, exist_ok=True)
if settings.mineru_enabled:
    settings.mineru_home.mkdir(parents=True, exist_ok=True)
    settings.mineru_temp_dir.mkdir(parents=True, exist_ok=True)
    settings.mineru_output_dir.mkdir(parents=True, exist_ok=True)

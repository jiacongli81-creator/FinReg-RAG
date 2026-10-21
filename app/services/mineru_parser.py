from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from ..config import settings


WORKER_PATH = Path(__file__).with_name("mineru_worker.py")


def mineru_status() -> dict[str, object]:
    return {
        "enabled": settings.mineru_enabled,
        "available": settings.mineru_enabled and settings.mineru_python.is_file() and WORKER_PATH.is_file(),
        "python": str(settings.mineru_python),
        "model_home": str(settings.mineru_home),
    }


def parse_with_mineru(path: Path) -> list[tuple[int, str]]:
    status = mineru_status()
    if not status["available"]:
        raise RuntimeError(
            f"MinerU 不可用，请检查 MINERU_PYTHON={settings.mineru_python} 和模型目录 {settings.mineru_home}"
        )

    fingerprint = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
    output_path = settings.mineru_output_dir / f"{path.stem}-{fingerprint}.json"
    environment = os.environ.copy()
    environment.update(
        {
            "MINERU_HOME": str(settings.mineru_home),
            "MINERU_MODEL_SOURCE": "local",
            "MINERU_MODEL_SMALL_BACKEND": "onnx",
            "TEMP": str(settings.mineru_temp_dir),
            "TMP": str(settings.mineru_temp_dir),
            "TMPDIR": str(settings.mineru_temp_dir),
            "HF_HOME": str(settings.mineru_home.parent / "cache" / "huggingface"),
            "MODELSCOPE_CACHE": str(settings.mineru_home.parent / "cache" / "modelscope"),
        }
    )

    process = subprocess.run(
        [str(settings.mineru_python), str(WORKER_PATH), str(path.resolve()), str(output_path)],
        cwd=str(settings.mineru_output_dir),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=settings.mineru_timeout_seconds,
        check=False,
    )
    if process.returncode != 0:
        details = (process.stderr or process.stdout or "未知错误").strip()
        raise RuntimeError(f"MinerU 解析失败: {details[-3000:]}")
    if not output_path.is_file():
        raise RuntimeError("MinerU 解析结束，但没有生成结果文件")

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    pages = [(int(item["page"]), str(item["text"])) for item in payload.get("pages", [])]
    if not pages:
        raise ValueError("MinerU 没有识别到可用于知识库的文字")
    return pages

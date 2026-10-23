import hashlib
import json
import math
import re
import urllib.error
import urllib.request

from ..config import settings


DIMENSION = 512


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    tokens: list[str] = []
    for word in words:
        tokens.append(word)
        if len(word) > 1 and all("\u4e00" <= char <= "\u9fff" for char in word):
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
    return tokens


def embed(text: str) -> list[float]:
    if settings.embedding_provider == "ollama":
        payload = json.dumps({"model": settings.embedding_model, "input": text}).encode("utf-8")
        request = urllib.request.Request(
            settings.embedding_base_url.rstrip("/") + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.embedding_timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"无法连接 Ollama ({settings.embedding_base_url})，请启动 Ollama 并确认模型 {settings.embedding_model} 已安装"
            ) from exc
        embeddings = result.get("embeddings")
        if not embeddings or not embeddings[0]:
            raise RuntimeError("Ollama 返回了空 embedding")
        return embeddings[0]
    if settings.embedding_provider != "hash":
        raise RuntimeError(f"不支持的 EMBEDDING_PROVIDER: {settings.embedding_provider}")
    vector = [0.0] * DIMENSION
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % DIMENSION
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))

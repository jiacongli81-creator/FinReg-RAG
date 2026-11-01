"""Cross encoder scoring of a question against retrieved source text."""

from functools import lru_cache

from ..config import settings


@lru_cache(maxsize=1)
def _model():
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as exc:
        raise RuntimeError("交叉编码器未安装，请运行 pip install -r requirements.txt") from exc
    options = {"model_name": settings.rerank_model, "cache_dir": str(settings.rerank_cache_dir)}
    try:
        return TextCrossEncoder(**options, local_files_only=True)
    except (OSError, ValueError):
        return TextCrossEncoder(**options)


def rerank_candidates(question: str, candidates: list[tuple[float, object]]) -> list[tuple[float, object]]:
    """Score each (question, full chunk text) pair without using gold evidence."""
    if not candidates:
        return []
    unique = []
    seen_content = set()
    for score, row in candidates:
        content = row["content"]
        if content not in seen_content:
            seen_content.add(content)
            unique.append((score, row))
    try:
        scores = list(_model().rerank(question, [row["content"] for _, row in unique]))
    except Exception as exc:
        raise RuntimeError(f"重排模型 {settings.rerank_model} 运行失败: {exc}") from exc
    if len(scores) != len(unique):
        raise RuntimeError("重排模型返回的分数数量与候选片段数量不符")
    scored = [(float(score), row) for score, (_, row) in zip(scores, unique)]
    return sorted(scored, key=lambda pair: (-pair[0], pair[1]["id"]))

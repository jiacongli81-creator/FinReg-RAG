import json
import re
import urllib.request

from ..config import settings
from .keywords import keywords


def generate_fast_answer(question: str, sources: list[dict]) -> tuple[str, str]:
    """Return short, cited source excerpts without a remote generation request."""
    if not sources:
        return "没有检索到足够的制度依据，暂时无法确认答案。", "low"
    query_terms = set(keywords(question))
    candidates = []
    for source_index, source in enumerate(sources, start=1):
        sentences = re.split(r"(?<=[。！？；])|\n+", source["content"])
        for position, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if len(sentence) < 8:
                continue
            overlap = len(query_terms & set(keywords(sentence)))
            candidates.append((overlap, source_index, position, sentence))
    if not candidates:
        return "没有检索到足够的制度依据，暂时无法确认答案。", "low"
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = []
    seen = set()
    for overlap, source_index, _, sentence in candidates:
        excerpt = sentence[:220] + ("…" if len(sentence) > 220 else "")
        if excerpt in seen:
            continue
        seen.add(excerpt)
        selected.append(f"{excerpt}[{source_index}]")
        if len(selected) == 2:
            break
    return "相关依据摘录：\n" + "\n".join(selected), "medium" if candidates[0][0] else "low"


def generate_answer(question: str, sources: list[dict]) -> tuple[str, str]:
    if settings.llm_provider != "openai_compatible":
        excerpts = "\n\n".join(f"[{index + 1}] {item['content']}" for index, item in enumerate(sources))
        if not excerpts:
            return "没有检索到足够的制度依据，暂时无法确认答案。", "low"
        return f"根据检索到的制度内容，相关依据如下：\n\n{excerpts}", "medium"

    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        raise RuntimeError("LLM_PROVIDER=openai_compatible requires LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
    context = "\n\n".join(f"[{index + 1}] {item['content']}" for index, item in enumerate(sources))
    payload = json.dumps(
        {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": "你是金融制度问答助手。只能依据资料回答，不能补充资料之外的事实。直接回答用户问题，不要使用‘根据给定资料’、‘依据给定资料’、‘给定资料显示’等固定开场，也不要复述问题。回答应简洁、自然；需要时在相关句末用[1]、[2]标注资料编号。资料不足时直接说‘现有资料不足以确认’，并简要说明缺少什么信息。"},
                {"role": "user", "content": f"参考资料：\n{context}\n\n用户问题：{question}\n\n请直接给出答案："},
            ],
            "temperature": 0.1,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        settings.llm_base_url.rstrip("/") + "/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.llm_api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"], "high"

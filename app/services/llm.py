import json
import urllib.request

from ..config import settings


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
                {"role": "system", "content": "你是金融制度问答助手。只能依据给定资料回答，必须引用资料编号；没有依据时明确说明无法确认。"},
                {"role": "user", "content": f"资料：\n{context}\n\n问题：{question}"},
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

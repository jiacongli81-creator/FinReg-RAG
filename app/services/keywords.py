"""Chinese keyword scoring for the existing document chunks."""

import math
import re
from collections import Counter
from functools import lru_cache

import jieba


STOPWORDS = frozenset("的 了 和 与 及 在 是 有 对 为 将 等 中 按 根据 关于 什么 如何 是否 哪些 请 问 一 个 我 你".split())
TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+", re.IGNORECASE)


def keywords(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.finditer(text.lower()):
        part = match.group()
        terms = jieba.lcut_for_search(part) if re.search(r"[\u4e00-\u9fff]", part) else [part]
        tokens.extend(term for term in terms if len(term) > 1 and term not in STOPWORDS)
    return tokens


@lru_cache(maxsize=10000)
def _chunk_terms(content: str, title: str) -> tuple[Counter, frozenset[str], int]:
    content_tokens = keywords(content)
    return Counter(content_tokens), frozenset(keywords(title)), len(content_tokens)


def rank_keywords(question: str, rows: list, limit: int = 50) -> list[tuple[float, object]]:
    query_terms = set(keywords(question))
    if not query_terms:
        return []

    tokenized = []
    document_frequency = Counter()
    for row in rows:
        counts, title_tokens, length = _chunk_terms(row["content"], row["title"])
        document_frequency.update(query_terms & (set(counts) | title_tokens))
        tokenized.append((row, counts, title_tokens, length))
    if not tokenized:
        return []

    average_length = sum(item[3] for item in tokenized) / len(tokenized) or 1
    ranked = []
    for row, counts, title_tokens, length in tokenized:
        score = 0.0
        for term in query_terms:
            frequency = counts[term]
            if not frequency and term not in title_tokens:
                continue
            inverse_frequency = math.log1p((len(rows) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            score += inverse_frequency * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average_length)) if frequency else 0
            if term in title_tokens:
                score += inverse_frequency * 1.5
        if score > 0:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    return ranked[:limit]

"""Separate, source-backed article library and explicit same-law citations."""

from __future__ import annotations

import re
import uuid
import math
from collections import Counter
from typing import Any

from .config import settings
from .db import connect, utc_now
from .services.keywords import keywords

HAN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
NUMBER = r"[零〇一二三四五六七八九十百千万\d]+"
ARTICLE_START = re.compile(rf"^第({NUMBER})\s*条(?:\s|$)")
CHAPTER_START = re.compile(rf"^第{NUMBER}章\s*(.*)$")
REFERENCE = re.compile(rf"第({NUMBER})条")


def article_number(value: str) -> int:
    if value.isdecimal():
        return int(value)
    total = 0
    section = 0
    digit = 0
    for char in value:
        if char in HAN_DIGITS:
            digit = HAN_DIGITS[char]
        elif char in "十百千":
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            section += (digit or 1) * unit
            digit = 0
        elif char == "万":
            total += (section + digit) * 10000
            section = digit = 0
        else:
            raise ValueError(f"Unsupported article number: {value}")
    return total + section + digit


def parse_articles(lines: list[str]) -> list[dict[str, Any]]:
    """Use paragraph/line boundaries so mentions inside a clause are not headings."""
    joined_lines = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if re.fullmatch(rf"第{NUMBER}", line) and index + 1 < len(lines) and lines[index + 1].strip().startswith("条"):
            line += lines[index + 1].strip()
            index += 1
        joined_lines.append(line)
        index += 1
    articles = []
    chapter = None
    current = None
    for raw in joined_lines:
        line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
        if not line:
            continue
        chapter_match = CHAPTER_START.match(line)
        if chapter_match:
            chapter = line
            continue
        match = ARTICLE_START.match(line)
        if match:
            number = article_number(match.group(1))
            if current:
                articles.append(current)
            label = f"第{match.group(1)}条"
            remainder = line[match.end():].strip()
            current = {"article_number": number, "article_label": f"第{match.group(1)}条",
                       "chapter": chapter, "content": label + (" " + remainder if remainder else "")}
        elif current:
            current["content"] += "\n" + line
    if current:
        articles.append(current)
    numbers = [article["article_number"] for article in articles]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"Article headings are incomplete or out of order: {numbers}")
    return articles


def explicit_references(article: dict[str, Any], available: set[int], law_title: str = "") -> list[dict[str, Any]]:
    """Link only same-law article mentions; exclude immediate quoted other-law titles."""
    body = article["content"][len(article["article_label"]):]
    found = []
    seen = set()
    for match in REFERENCE.finditer(body):
        number = article_number(match.group(1))
        if number == article["article_number"] or number not in available:
            continue
        preceding = body[max(body.rfind("。", 0, match.start()), body.rfind("；", 0, match.start()), body.rfind("\n", 0, match.start())) + 1:match.start()]
        contexts = list(re.finditer(r"《[^》]+》|本法|本条例", preceding))
        latest = contexts[-1].group(0) if contexts else ""
        if latest.startswith("《") and latest[1:-1] != law_title:
            continue
        if number not in seen:
            seen.add(number)
            found.append({"to_number": number, "evidence": match.group(0)})
    return found


def _execute(sql: str, params: tuple = (), *, many: bool = False) -> list[dict]:
    with connect() as conn:
        if settings.database_backend == "mysql":
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.executemany(sql, params) if many else cursor.execute(sql, params)
                return cursor.fetchall() if cursor.with_rows else []
            finally:
                cursor.close()
        cursor = conn.cursor()
        try:
            cursor.executemany(sql, params) if many else cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()] if cursor.description else []
        finally:
            cursor.close()


def _p() -> str:
    return "%s" if settings.database_backend == "mysql" else "?"


def init_law_db() -> None:
    if settings.database_backend == "mysql":
        statements = [
            """CREATE TABLE IF NOT EXISTS law_documents (id VARCHAR(36) PRIMARY KEY,
               title VARCHAR(255) NOT NULL, version_note TEXT NOT NULL,
               source_url TEXT NOT NULL, source_sha256 CHAR(64) NOT NULL,
               fetched_at VARCHAR(64) NOT NULL, raw_html LONGTEXT NOT NULL,
               article_count INT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS law_articles (id VARCHAR(36) PRIMARY KEY,
               law_id VARCHAR(36) NOT NULL, article_number INT NOT NULL,
               article_label VARCHAR(32) NOT NULL, chapter VARCHAR(255),
               content LONGTEXT NOT NULL, UNIQUE KEY uq_law_number (law_id, article_number),
               FOREIGN KEY (law_id) REFERENCES law_documents(id) ON DELETE CASCADE)
               ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
            """CREATE TABLE IF NOT EXISTS law_references (from_article_id VARCHAR(36) NOT NULL,
               to_article_id VARCHAR(36) NOT NULL, evidence VARCHAR(64) NOT NULL,
               PRIMARY KEY (from_article_id, to_article_id),
               KEY idx_law_references_to (to_article_id),
               FOREIGN KEY (from_article_id) REFERENCES law_articles(id) ON DELETE CASCADE,
               FOREIGN KEY (to_article_id) REFERENCES law_articles(id) ON DELETE CASCADE)
               ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        ]
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS law_documents (id TEXT PRIMARY KEY, title TEXT NOT NULL,
               version_note TEXT NOT NULL, source_url TEXT NOT NULL, source_sha256 TEXT NOT NULL,
               fetched_at TEXT NOT NULL, raw_html TEXT NOT NULL, article_count INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS law_articles (id TEXT PRIMARY KEY, law_id TEXT NOT NULL,
               article_number INTEGER NOT NULL, article_label TEXT NOT NULL, chapter TEXT,
               content TEXT NOT NULL, UNIQUE(law_id, article_number))""",
            """CREATE TABLE IF NOT EXISTS law_references (from_article_id TEXT NOT NULL,
               to_article_id TEXT NOT NULL, evidence TEXT NOT NULL,
               PRIMARY KEY (from_article_id, to_article_id))""",
            "CREATE INDEX IF NOT EXISTS idx_law_articles_law ON law_articles(law_id)",
            "CREATE INDEX IF NOT EXISTS idx_law_refs_to ON law_references(to_article_id)",
        ]
    with connect() as conn:
        cursor = conn.cursor()
        try:
            for sql in statements:
                cursor.execute(sql)
        finally:
            cursor.close()


def import_law(*, title: str, version_note: str, source_url: str, source_sha256: str,
               raw_html: str, articles: list[dict[str, Any]]) -> dict:
    if not articles:
        raise ValueError("Cannot import a law without articles")
    law_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source_url))
    ids = {article["article_number"]: str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_url}#{article['article_number']}")) for article in articles}
    refs = [
        (ids[article["article_number"]], ids[ref["to_number"]], ref["evidence"])
        for article in articles for ref in explicit_references(article, set(ids), title)
    ]
    p = _p()
    with connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT source_sha256 FROM law_documents WHERE id={p}", (law_id,))
            previous = cursor.fetchone()
            if previous and previous[0] == source_sha256:
                return {"law_id": law_id, "article_count": len(articles), "reference_count": len(refs), "changed": False}
            if previous:
                raise ValueError("Official source content changed; review the version before replacing saved articles")
            cursor.execute(f"INSERT INTO law_documents (id,title,version_note,source_url,source_sha256,fetched_at,raw_html,article_count) VALUES ({','.join([p]*8)})",
                           (law_id, title, version_note, source_url, source_sha256, utc_now(), raw_html, len(articles)))
            cursor.executemany(f"INSERT INTO law_articles (id,law_id,article_number,article_label,chapter,content) VALUES ({','.join([p]*6)})",
                               [(ids[a["article_number"]], law_id, a["article_number"], a["article_label"], a["chapter"], a["content"]) for a in articles])
            if refs:
                cursor.executemany(f"INSERT INTO law_references (from_article_id,to_article_id,evidence) VALUES ({','.join([p]*3)})", refs)
        except BaseException:
            conn.rollback()
            raise
        finally:
            cursor.close()
    return {"law_id": law_id, "article_count": len(articles), "reference_count": len(refs), "changed": True}


def list_laws() -> list[dict]:
    return _execute("SELECT id,title,version_note,source_url,source_sha256,fetched_at,article_count FROM law_documents ORDER BY title,id")


def search_articles(query: str, law_id: str | None = None, limit: int = 30, offset: int = 0) -> list[dict]:
    query = query.strip()
    if len(query) > 200:
        raise ValueError("Query is too long")
    if offset < 0:
        raise ValueError("Offset must be nonnegative")
    p = _p()
    sql = "SELECT a.id,a.law_id,d.title,d.version_note,d.source_url,a.article_number,a.article_label,a.chapter,a.content FROM law_articles a JOIN law_documents d ON d.id=a.law_id WHERE 1=1"
    params: list[Any] = []
    if law_id:
        sql += f" AND a.law_id={p}"
        params.append(law_id)
    if query:
        num = None
        match = ARTICLE_START.match(query)
        if match and match.end() == len(query):
            num = article_number(match.group(1))
        elif query.isdecimal():
            num = int(query)
        if num is not None:
            sql += f" AND a.article_number={p}"
            params.append(num)
        else:
            sql += f" AND (a.content LIKE {p} OR d.title LIKE {p})"
            params.extend([f"%{query}%", f"%{query}%"])
    sql += f" ORDER BY d.title,a.article_number LIMIT {p} OFFSET {p}"
    params.append(min(max(limit, 1), 100))
    params.append(offset)
    return _execute(sql, tuple(params))


def get_article(article_id: str) -> dict | None:
    p = _p()
    found = _execute(f"SELECT a.id,a.law_id,d.title,d.version_note,d.source_url,d.fetched_at,a.article_number,a.article_label,a.chapter,a.content FROM law_articles a JOIN law_documents d ON d.id=a.law_id WHERE a.id={p}", (article_id,))
    if not found:
        return None
    article = found[0]
    for direction, column, other in (("references", "from_article_id", "to_article_id"), ("referenced_by", "to_article_id", "from_article_id")):
        article[direction] = _execute(
            f"SELECT a.id,a.article_number,a.article_label,a.chapter,a.content,r.evidence FROM law_references r JOIN law_articles a ON a.id=r.{other} WHERE r.{column}={p} ORDER BY a.article_number", (article_id,)
        )
    article["similar_articles"] = similar_articles(article, limit=5)
    return article


def similar_articles(article: dict, limit: int = 5) -> list[dict]:
    """Text similarity suggestions, separate from authoritative citation edges."""
    rows = _execute("SELECT a.id,a.law_id,a.article_number,a.article_label,a.chapter,a.content,d.title,d.version_note,d.source_url FROM law_articles a JOIN law_documents d ON d.id=a.law_id")
    if not rows:
        return []
    direct_ids = {row["id"] for row in article.get("references", []) + article.get("referenced_by", [])}
    target = Counter(keywords(article["content"][len(article["article_label"]):]))
    terms = {row["id"]: Counter(keywords(row["content"][len(row["article_label"]):])) for row in rows}
    frequencies = Counter(term for counts in terms.values() for term in counts)

    def vector(counts: Counter) -> dict[str, float]:
        return {term: (1 + math.log(count)) * math.log1p(len(rows) / (frequencies[term] + 1))
                for term, count in counts.items() if frequencies[term] < len(rows) * 0.8}

    target_vector = vector(target)
    target_norm = math.sqrt(sum(value * value for value in target_vector.values())) or 1
    ranked = []
    for row in rows:
        if row["id"] == article["id"] or row["id"] in direct_ids:
            continue
        other = vector(terms[row["id"]])
        norm = math.sqrt(sum(value * value for value in other.values())) or 1
        score = sum(value * other.get(term, 0) for term, value in target_vector.items()) / (target_norm * norm)
        if score > 0.05:
            ranked.append({**row, "similarity_score": round(score, 4)})
    ranked.sort(key=lambda row: (-row["similarity_score"], row["law_id"], row["article_number"]))
    return ranked[:limit]

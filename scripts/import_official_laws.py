"""Fetch reviewed official full texts into the separate law article tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import init_db
from app.law_library import import_law, init_law_db, parse_articles

SOURCES = (
    {
        "title": "中华人民共和国人民币管理条例",
        "version_note": "国务院公报2019年第1号刊载；2000年发布，2014年、2018年修订文本",
        "url": "https://www.gov.cn/gongbao/content/2019/content_5468922.htm",
        "selector": "#UCAP-CONTENT",
        "expected_articles": 47,
    },
    {
        "title": "中华人民共和国银行业监督管理法",
        "version_note": "中国人民银行网站刊载；2003年通过，2006年修正文本",
        "url": "https://www.pbc.gov.cn/tiaofasi/144941/144951/3808036/index.html",
        "selector": "#zoom",
        "expected_articles": 52,
    },
    {
        "title": "中华人民共和国证券法",
        "version_note": "全国人大网站刊载；2019年修订文本，2020年3月1日起施行",
        "url": "http://www.npc.gov.cn/npc/c2/c30834/201912/t20191231_304436.html",
        "selector": "#Zoom",
        "expected_articles": 226,
    },
    {
        "title": "中华人民共和国反洗钱法",
        "version_note": "中国政府网刊载；2024年修订文本，2025年1月1日起施行",
        "url": "https://www.gov.cn/yaowen/liebiao/202411/content_6985765.htm",
        "selector": "#UCAP-CONTENT",
        "expected_articles": 65,
    },
    {
        "title": "中华人民共和国保险法",
        "version_note": "国家金融监督管理总局网站刊载；2015年修正文本",
        "url": "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=879931&itemId=4248&generaltype=0",
        "api_url": "https://www.nfra.gov.cn/cn/static/data/DocInfo/SelectByDocId/data_docId=879931.json",
        "expected_articles": 185,
    },
    {
        "title": "中华人民共和国商业银行法",
        "version_note": "国家金融监督管理总局网站刊载；2015年修正文本",
        "url": "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=879929&itemId=927&generaltype=0",
        "api_url": "https://www.nfra.gov.cn/cn/static/data/DocInfo/SelectByDocId/data_docId=879929.json",
        "expected_articles": 95,
    },
    {
        "title": "存款保险条例",
        "version_note": "国务院令第660号；2015年5月1日起施行",
        "url": "https://www.gov.cn/zhengce/content/2015-03/31/content_9562.htm",
        "selector": "#UCAP-CONTENT",
        "expected_articles": 23,
    },
    {
        "title": "征信业管理条例",
        "version_note": "国务院令第631号；2013年3月15日起施行",
        "url": "https://www.gov.cn/zwgk/2013-01/29/content_2322231.htm",
        "selector": "#Zoom",
        "expected_articles": 47,
    },
)


def fetch_source(spec: dict) -> tuple[str, str, list[dict]]:
    response = requests.get(spec.get("api_url", spec["url"]), timeout=30, headers={"User-Agent": "FinReg-RAG/1.0 law-source-import"})
    response.raise_for_status()
    if "api_url" in spec:
        payload = response.json()
        data = payload.get("data") or {}
        if data.get("docTitle") != spec["title"] or not data.get("docClob"):
            raise ValueError(f"Unexpected official document payload: {spec['api_url']}")
        html = data["docClob"]
        raw = html.encode("utf-8")
        body = BeautifulSoup(html, "html.parser")
    else:
        raw = response.content
        html = raw.decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        body = soup.select_one(spec["selector"])
        if body is None:
            raise ValueError(f"Official article container not found: {spec['url']}")
        if spec["title"] not in soup.get_text(" ", strip=True):
            raise ValueError(f"Expected law title missing: {spec['url']}")
    lines = body.get_text("\n", strip=True).splitlines()
    articles = parse_articles(lines)
    if len(articles) != spec["expected_articles"]:
        raise ValueError(f"Expected {spec['expected_articles']} articles, found {len(articles)}: {spec['url']}")
    if any("\ufffd" in a["content"] for a in articles):
        raise ValueError(f"Official source contains replacement characters: {spec['url']}")
    return html, hashlib.sha256(raw).hexdigest(), articles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true", help="Download and validate without writing the database")
    args = parser.parse_args()
    payloads = []
    for spec in SOURCES:
        html, digest, articles = fetch_source(spec)
        payloads.append((spec, html, digest, articles))
        print(json.dumps({"title": spec["title"], "url": spec["url"], "articles": len(articles), "sha256": digest}, ensure_ascii=False), flush=True)
    if args.validate_only:
        return 0
    init_db()
    init_law_db()
    for spec, html, digest, articles in payloads:
        result = import_law(title=spec["title"], version_note=spec["version_note"],
                            source_url=spec["url"], source_sha256=digest,
                            raw_html=html, articles=articles)
        print(json.dumps({"title": spec["title"], **result}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

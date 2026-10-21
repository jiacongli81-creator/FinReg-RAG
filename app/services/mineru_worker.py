from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from mineru.parser import parse


PAGE_SEPARATOR = "\n\n---\n\n"
DATA_IMAGE_PATTERN = re.compile(
    r"!\[[^]]*\]\(data:image/[^;\s)]+;base64,[A-Za-z0-9+/=\r\n]+\)",
    re.IGNORECASE,
)
HTML_DATA_IMAGE_PATTERN = re.compile(
    r"<img\b[^>]*?src=[\"']data:image/[^;\"']+;base64,[^\"']+[\"'][^>]*>",
    re.IGNORECASE | re.DOTALL,
)
RAW_DATA_IMAGE_PATTERN = re.compile(
    r"data:image/[^;\s\"']+;base64,[A-Za-z0-9+/=\r\n]+",
    re.IGNORECASE,
)


def clean_markdown(text: str) -> str:
    text = DATA_IMAGE_PATTERN.sub("", text)
    text = HTML_DATA_IMAGE_PATTERN.sub("", text)
    text = RAW_DATA_IMAGE_PATTERN.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mineru_worker.py INPUT OUTPUT_JSON")

    input_path = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    suffix = input_path.suffix.lower()
    tier = "basic" if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".jp2"} else "flash"
    ocr_mode = "ocr" if suffix != ".pdf" and tier == "basic" else "auto"

    result = parse(input_path, tier=tier, ocr_mode=ocr_mode, image_analysis=False)
    rendered = result.markdown(add_markers=True)
    rendered_pages = rendered.split(PAGE_SEPARATOR)
    page_indices = [page.page_idx for page in result.pages]

    pages = []
    for index, text in enumerate(rendered_pages):
        cleaned = clean_markdown(text)
        if cleaned:
            page_number = page_indices[index] + 1 if index < len(page_indices) else index + 1
            pages.append({"page": page_number, "text": cleaned})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {"source": str(input_path), "tier": tier, "page_count": len(result.pages), "pages": pages},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Convert legacy .doc/.wps files to .docx without changing the originals.

This script uses the locally installed Microsoft Word through COM automation.
It is Windows-only and requires Microsoft Word plus pywin32.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path


LEGACY_EXTENSIONS = {".doc", ".wps"}


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Convert .doc/.wps files to .docx")
    parser.add_argument("--input", type=Path, default=root / "data" / "raw")
    parser.add_argument("--output", type=Path, default=root / "data" / "converted")
    parser.add_argument("--report", type=Path, default=root / "data" / "conversion_report.csv")
    parser.add_argument("--limit", type=int, default=0, help="Only convert the first N files; 0 means all")
    return parser.parse_args()


def convert_all(input_dir: Path, output_dir: Path, report_path: Path, limit: int = 0) -> int:
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        print("缺少 pywin32，请先执行: python -m pip install pywin32", file=sys.stderr)
        return 2

    files = sorted(
        path for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in LEGACY_EXTENSIONS
    )
    if limit > 0:
        files = files[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    word = None
    rows: list[dict[str, str]] = []
    try:
        pythoncom.CoInitialize()
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        for source in files:
            relative = source.relative_to(input_dir)
            target = output_dir / relative.with_suffix(".docx")
            target.parent.mkdir(parents=True, exist_ok=True)
            row = {"source": str(source), "target": str(target), "status": "failed", "error": ""}
            document = None
            try:
                document = word.Documents.Open(
                    str(source.resolve()),
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                    Visible=False,
                )
                document.SaveAs2(str(target.resolve()), FileFormat=16)
                document.Close(SaveChanges=False)
                document = None
                row["status"] = "converted"
            except Exception as exc:  # COM errors vary by Office version/file type.
                row["error"] = str(exc).replace("\r", " ").replace("\n", " ")
                if document is not None:
                    try:
                        document.Close(SaveChanges=False)
                    except Exception:
                        pass
            rows.append(row)
            print(f"[{row['status']}] {source.name}")
            time.sleep(0.1)
    finally:
        if word is not None:
            word.Quit(SaveChanges=False)
        pythoncom.CoUninitialize()

    with report_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=["source", "target", "status", "error"])
        writer.writeheader()
        writer.writerows(rows)
    converted = sum(row["status"] == "converted" for row in rows)
    failed = len(rows) - converted
    print(f"完成：共 {len(rows)} 个，成功 {converted} 个，失败 {failed} 个")
    print(f"转换结果：{output_dir.resolve()}")
    print(f"报告：{report_path.resolve()}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(convert_all(args.input, args.output, args.report, args.limit))

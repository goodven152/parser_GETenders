# keyword_tester.py
"""
Проверка любых документов на ключевые слова.
$ python keyword_tester.py путь/к/файлу1.xlsx [файл2.pdf ...]
$ python keyword_tester.py sample.docx --kw "სარქველი,ურდুলি"
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from ge_parser_tenders.config import settings
from ge_parser_tenders.extractor import file_contains_keywords


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", type=Path, help="Документы для проверки")
    p.add_argument(
        "--kw",
        help="Слова через запятую; если не задано — берём из config.json",
    )
    return p.parse_args()


def _load_kw(raw: str | None) -> List[str]:
    if raw:
        return [w.strip() for w in raw.split(",") if w.strip()]
    return settings.keywords_geo


def main() -> None:
    args = _args()
    kw = _load_kw(args.kw)

    if not kw:
        raise SystemExit("❌ нет ключевых слов для поиска")

    for f in args.files:
        if not f.exists():
            print(f"⚠️  {f} — файл не найден")
            continue

        hit = file_contains_keywords(f, kw)
        print(f'{"HIT" if hit else "OK "}  {f.name}')


if __name__ == "__main__":
    main()

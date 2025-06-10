"""
keyword_tester.py
~~~~~~~~~~~~~~~~~
Утилита для локальной проверки любых документов на наличие «запрещённых»
или просто заданных ключевых слов.

Примеры запуска
---------------

# 1. Проверить файл(ы) c ключевыми словами из config.json
$ python keyword_tester.py docs/დანართი.xlsx another.pdf

# 2. То же, но задать слова вручную
$ python keyword_tester.py sample.docx --kw "სარქველი,ურდული"

Вывод
-----
HIT <имя_файла>  – найдено хотя бы одно слово
OK  <имя_файла>  – слов нет
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from ge_parser_tenders.config import settings          # ключевые из конфига
from ge_parser_tenders.extractor import file_contains_keywords

# ──────────────────────────── helpers ────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Проверка документов на наличие ключевых слов."
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Путь(и) к файлам (Excel, PDF, DOCX и т.д.)",
    )
    parser.add_argument(
        "--kw",
        metavar="WORDS",
        help='Ключевые слова через запятую (например: "სარქველი,ურდული"). '
        "Если не указано — используются слова из config.json",
    )
    return parser.parse_args()


def _load_keywords(custom_kw: str | None) -> List[str]:
    """Возвращает список ключевых слов для поиска."""
    if custom_kw:
        return [k.strip() for k in custom_kw.split(",") if k.strip()]
    return settings.keywords_geo


# ──────────────────────────── main ───────────────────────────────


def main() -> None:
    args = _parse_args()
    keywords = _load_keywords(args.kw)

    if not keywords:
        raise SystemExit("❌ Нет ключевых слов для поиска (список пуст).")

    for file_path in args.files:
        if not file_path.exists():
            print(f"⚠️  {file_path} — файл не найден")
            continue

        hit = file_contains_keywords(file_path, keywords)
        status = "HIT" if hit else "OK "
        print(f"{status}  {file_path.name}")


if __name__ == "__main__":
    main()

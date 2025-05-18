"""
Извлечение текста + поиск ключевых слов с подробным логгированием
----------------------------------------------------------------
* поддерживает .pdf / .xls / .xlsx
* быстрейший порядок: pypdf → pdftotext(poppler) → pandas-excel
* fuzzy-поиск (RapidFuzz) + при наличии Stanza — лемматизация
"""
from __future__ import annotations
from pathlib import Path
import logging
import shlex
from subprocess import run, PIPE

import pandas as pd

from .config import KEYWORDS_GEO, KEYWORDS_RE          # regex + список
from .text_matcher import find_keyword_hits            # ← из вашего text_matcher.py
from .ocr_image import extract_pdf_ocr

DEFAULT_THRESHOLD = 80


# --------------------------------------------------------------------------- #
#                       helpers: pdf / excel  →  text                         #
# --------------------------------------------------------------------------- #
def _pdf_to_text_poppler(path: Path) -> str:
    cmd = f"pdftotext -layout -enc UTF-8 {shlex.quote(str(path))} -"
    proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE, timeout=60)
    return proc.stdout.decode("utf-8", "ignore")


def _xlsx_to_text(path: Path) -> str:
    engine = "openpyxl" if path.suffix == ".xlsx" else "xlrd"
    df = pd.read_excel(path, dtype=str, header=None, engine=engine)
    return "\n".join(df.fillna("").astype(str).agg("\t".join, axis=1))


def extract_text(file_path: Path) -> str:
    suf = file_path.suffix.lower()
    if suf == ".pdf":
        text = ""
        try:                                         # 1) pypdf
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(file_path).pages)
            if len(text.strip()) >= 50:
                return text
            logging.debug("    pypdf дал мало текста (%d симв.) – пробуем дальше", len(text))
        except Exception as exc:
            logging.debug("    pypdf failed (%s) – пробуем дальше", exc)
        try:                                         # 2)  poppler           
            text = _pdf_to_text_poppler(file_path)
            if len(text.strip()) >= 50:
                return text
            logging.debug("    poppler дал мало текста (%d симв.) – идём в OCR", len(text))
        except Exception as exc:
            logging.debug("    poppler failed (%s) – идём в OCR", exc)
        try:                                         # 3)  tesseract-ocr
            return extract_pdf_ocr(file_path)
        except Exception as exc:
            logging.warning("%s: OCR failed (%s)", file_path.name, exc)

    if suf in {".xls", ".xlsx"}:                     # Excel
        try:
            return _xlsx_to_text(file_path)
        except Exception as exc:
            logging.warning("%s: excel-extract failed (%s)", file_path.name, exc)

    return ""


# --------------------------------------------------------------------------- #
#                             public API                                      #
# --------------------------------------------------------------------------- #
def file_contains_keywords(
    file_path: Path,
    *,
    threshold: int = DEFAULT_THRESHOLD,
) -> bool:
    """
    Возвращает True, если в документе ≥ одно ключевое слово
    (fuzzy-score ≥ *threshold*).  Пишет подробный лог, повторяя
    поведение `keyword_tester.py`.
    """
    logging.info("🔍 Сканируем %s", file_path.name)

    text = extract_text(file_path)
    if not text.strip():
        logging.info("    пустой/не распознан")
        return False
    logging.info("    извлечено %d символов", len(text))

    # ── быстрый префильтр regex ― резко сокращает количество fuzzy-сравнений
    if not KEYWORDS_RE.search(text):
        logging.debug("    regex промахнулся — переходим к fuzzy + леммам")
    else:
        logging.debug("    ⚡ regex совпал — уточняем fuzzy-скор")

    hits = find_keyword_hits(text, KEYWORDS_GEO, threshold=threshold)
    logging.info("    найдено %d ключевых слов (≥%d)", len(hits), threshold)

    # детальный список (DEBUG-уровень)
    if hits and logging.getLogger().isEnabledFor(logging.DEBUG):
        for kw, score in sorted(hits.items(), key=lambda t: -t[1]):
            logging.debug("        %-60s  score=%d", kw, score)

    return bool(hits)

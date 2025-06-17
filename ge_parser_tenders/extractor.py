"""
Извлечение текста + поиск ключевых слов с подробным логгированием
----------------------------------------------------------------
* поддерживает .pdf / .xls / .xlsx
* быстрейший порядок: pypdf → pdftotext(poppler) → pandas-excel
* fuzzy-поиск (RapidFuzz) + при наличии Stanza — лемматизация
"""
from __future__ import annotations

import gc
import time
import logging
import shlex
import re
import pandas as pd

from pathlib import Path
from subprocess import run, PIPE
from pypdf import PdfReader

from ge_parser_tenders.memory_manager import MemoryManager

from .config import ParserSettings       # regex + список
from .text_matcher import find_keyword_hits            # ← из вашего text_matcher.py
from .ocr_image import extract_pdf_ocr


class PDFTextExtractor:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.reader = None
        self._text = None

    def __enter__(self):
        self.reader = PdfReader(self.file_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.reader:
            # Пытаемся закрыть поток, если он существует
            try:
                self.reader.stream.close()
            except AttributeError:
                pass
        self.reader = None
        self._text = None
        gc.collect()  # Принудительная очистка памяти

    def extract_text(self) -> str:
        if self._text is None:
            try:
                text_parts = []
                for i, page in enumerate(self.reader.pages):
                    text_parts.append(page.extract_text() or "")
                    if (i + 1) % 10 == 0:
                        gc.collect()
                self._text = "\n".join(text_parts)
            except Exception as e:
                logging.error(f"Error extracting text: {e}")
                self._text = ""
        return self._text
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
    if not file_path.exists() or file_path.stat().st_size == 0:
        return ""
    suf = file_path.suffix.lower()
    if suf == ".pdf":
        # text = ""
        # 1) pypdf
        try:    
            with PDFTextExtractor(file_path) as extractor:                                     
                text = "\n".join((p.extract_text() or "") for p in PdfReader(file_path).pages)
                if len(text.strip()) >= 50:
                    return text
                logging.debug("    pypdf дал мало текста (%d симв.) – пробуем дальше", len(text))
        except Exception as exc:
            logging.debug("    pypdf failed (%s) – пробуем дальше", exc)
        finally:
            gc.collect()
        # 2)  poppler
        try:                                                    
            text = _pdf_to_text_poppler(file_path)
            if len(text.strip()) >= 50:
                return text
            logging.debug("    poppler дал мало текста (%d симв.) – идём в OCR", len(text))
        except Exception as exc:
            logging.debug("    poppler failed (%s) – идём в OCR", exc)
        finally:
            gc.collect()
        # 3)  tesseract-ocr
        try:                                         
            return extract_pdf_ocr(file_path)
        except Exception as exc:
            logging.warning("%s: OCR failed (%s)", file_path.name, exc)
        finally:
            gc.collect()
    # Excel
    if suf in {".xls", ".xlsx"}:                     
        try:
            return _xlsx_to_text(file_path)
        except Exception as exc:
            logging.warning("%s: excel-extract failed (%s)", file_path.name, exc)
        finally:
            gc.collect()
    return ""


# --------------------------------------------------------------------------- #
#                             public API                                      #
# --------------------------------------------------------------------------- #
def file_contains_keywords(
    file_path: Path,
    settings: ParserSettings,
    *,
    threshold: int | None = None,
    memory_manager: MemoryManager | None = None,
) -> bool:
    if memory_manager and not memory_manager.check_memory():
        logging.info("Memory too high, skipping file")
        return False
    """
    Возвращает True, если в документе ≥ одно ключевое слово
    (fuzzy-score ≥ *threshold*).  Пишет подробный лог, повторяя
    поведение `keyword_tester.py`.
    """
    logging.info("  Сканируем %s", file_path.name)
    try:
        text = extract_text(file_path)
    except Exception as exc:
        logging.error("  Ошибка при извлечении текста: %s", exc)
        return ""
    if not text.strip():
        logging.info("  пустой/не распознан")
        return False
    logging.info("  Извлечено %d символов", len(text))
    logging.info("  Начинаем поиск ключевых слов…")

    # ── быстрый префильтр regex ― резко сокращает количество fuzzy-сравнений
    if not re.compile("|".join(map(re.escape, settings.keywords_geo)), flags=re.I).search(text):
        logging.debug("  regex промахнулся — переходим к fuzzy + леммам")
    else:
        logging.debug(" regex совпал — уточняем fuzzy-скор")

    # ── fuzzy-поиск ключевых слов
    thresh = threshold or settings.fuzzy_threshold
    try:
        hits = find_keyword_hits(text, settings.keywords_geo, threshold=thresh)
    except Exception as exc:
        logging.error("  Ошибка при поиске ключевых слов: %s", exc)
        return False
    logging.info(" Найдено %d ключевых слов (≥%d)\n", len(hits), thresh)

    # детальный список (DEBUG-уровень)
    if hits and logging.getLogger().isEnabledFor(logging.DEBUG):
        for kw, score in sorted(hits.items(), key=lambda t: -t[1]):
            logging.debug("        %-60s  score=%d", kw, score)

    return bool(hits)

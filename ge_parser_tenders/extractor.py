import shutil
import tempfile
import pandas as pd
from pathlib import Path
import logging
import requests
from .config import KEYWORDS_RE
from subprocess import run, PIPE
import shlex

def _pdf_to_text_poppler(path: Path) -> str:
    """Пытаемся самым быстрым способом: pdftotext (Poppler)."""
    cmd = f"pdftotext -layout -enc UTF-8 {shlex.quote(str(path))} -"
    proc = run(cmd, shell=True, stdout=PIPE, stderr=PIPE, timeout=60)
    return proc.stdout.decode("utf-8", "ignore")

def _xlsx_to_text(path: Path) -> str:
    engine = "openpyxl" if path.suffix == ".xlsx" else "xlrd"
    df = pd.read_excel(path, dtype=str, header=None, engine=engine)
    df = df.fillna("").astype(str)
    return "\n".join(df.agg("\t".join, axis=1))

def extract_text(file_path: Path) -> str:
    suf = file_path.suffix.lower()
    if suf in {".pdf"}:
        # 1) сначала pypdf (быстро, без внешних бинарей)
        try:
            from pypdf import PdfReader
            return "\n".join(((p.extract_text() or "") for p in PdfReader(file_path).pages))
        except Exception:
            pass
        # 2) затем poppler (надо поставить `choco install poppler` или apt/brew)
        try:
            return _pdf_to_text_poppler(file_path)
        except Exception:
            pass
    if suf in {".xls", ".xlsx"}:
        try:
            return _xlsx_to_text(file_path)
        except Exception as exc:
            logging.warning("%s: excel extract failed (%s)", file_path.name, exc)
            return ""

def file_contains_keywords(file_path: Path) -> bool:
    return bool(KEYWORDS_RE.search(extract_text(file_path)))
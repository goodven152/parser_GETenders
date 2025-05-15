import shutil
import tempfile
from pathlib import Path
import logging
import requests
from .config import KEYWORDS_RE

def extract_text(file_path: Path) -> str:
    safe_path = file_path.as_posix()
    """Return plain text extracted from *file_path* using textract."""
    try:
        import textract  # heavy import
        return textract.process(safe_path).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        logging.warning("%s: fallback failed (%s)", file_path.name, exc)

    if file_path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader  # pip install pypdf
            reader = PdfReader(safe_path)
            return "\n".join(
                (page.extract_text() or "") for page in reader.pages
            )
        except Exception as exc2:
            logging.warning("%s: second fallback failed (%s)", file_path.name, exc2)

    return ""

def file_contains_keywords(file_path: Path) -> bool:
    return bool(KEYWORDS_RE.search(extract_text(file_path)))
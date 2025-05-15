import shutil
import tempfile
from pathlib import Path
import logging
import requests

from .config import KEYWORDS_RE

def extract_text(file_path: Path) -> str:
    """Return plain text extracted from *file_path* using textract."""
    try:
        import textract  # heavy import
        return textract.process(str(file_path)).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        logging.warning("%s: fallback failed (%s)", file_path.name, exc)
        return ""
    
def file_contains_keywords(file_path: Path) -> bool:
    text = extract_text(file_path)
    return bool(KEYWORDS_RE.search(text))
# ge_parser_tenders/ocr_image.py
from __future__ import annotations
from pathlib import Path
import logging
import tempfile

from pdf2image import convert_from_path          # poppler
import pytesseract                               # tesseract-ocr ≥ 5.3
from PIL import Image

__all__ = ["extract_pdf_ocr"]

# ──────────────────────────────────────────────────────────────────────────
# one-page OCR helper
def _ocr_image(img: Image.Image, lang: str = "ka+eng") -> str:
    # Tesseract 5: download traineddata 'ka' once: `tesseract --list-langs`
    return pytesseract.image_to_string(img, lang=lang, config="--psm 6")

def extract_pdf_ocr(pdf_path: Path, *, dpi: int = 300) -> str:
    """
    Конвертирует страницы в PNG → скармливает Tesseract.
    Возвращает concatenated-текст всего файла.
    """
    logging.info("    🖼  OCR-экстракция (pdf2image, %d dpi)…", dpi)
    text_parts: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        images = convert_from_path(
            pdf_path, dpi=dpi, output_folder=tmp, fmt="png",
            thread_count=4, single_file=False
        )
        for idx, img in enumerate(images, 1):
            logging.debug("        ▸ страница %02d", idx)
            ocr = _ocr_image(img)
            text_parts.append(ocr)
    return "\n".join(text_parts)

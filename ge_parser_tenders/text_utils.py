# parser_getenders/text_utils.py
import re
import unicodedata
import functools
import gc
import logging
from typing import Optional
from .memory_manager import MemoryManager

GE_WORD_BOUND = r"(?:^|[^\u10A0-\u10FF])"  # граница не-грузинской буквы

def normalize(text: str) -> str:
    """NFC + lower + схлопывание пробельных последовательностей."""
    text = unicodedata.normalize("NFC", str(text))
    return " ".join(text.split()).lower()

@functools.lru_cache(maxsize=256)
def _kw_regex(kw: str) -> re.Pattern:
    """Регулярка «целое грузинское слово kw»."""
    return re.compile(f"{GE_WORD_BOUND}{re.escape(kw)}{GE_WORD_BOUND}", re.I)

def has_keyword(text: str, keywords: list[str], *, memory_manager: Optional[MemoryManager] = None) -> bool:
    if not text.strip():
        return False

    if memory_manager and not memory_manager.check_memory():
        logging.warning("MemoryManager: memory critical before normalization")
        gc.collect()

    nt = normalize(text)

    if memory_manager:
        memory_manager.force_cleanup()
    gc.collect()

    return any(_kw_regex(kw).search(nt) for kw in keywords)

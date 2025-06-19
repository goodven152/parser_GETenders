from __future__ import annotations
import stanza
import logging
import re
import gc

from pathlib import Path
from typing import Dict, List
from rapidfuzz import fuzz
from .memory_manager import MemoryManager

GE_RANGE = "ა-ჰ"                        # груз. алфавит mkhedruli

__all__ = ["contains_keywords", "find_keyword_hits"]

# ────────────────── Stanza init ──────────────────
try:
    _NLP = stanza.Pipeline(
        "ka",
        processors="tokenize,pos,lemma",
        tokenize_no_ssplit=True,
        use_gpu=False,
        logging_level="WARN",
    )
except Exception as exc:
    logging.warning("Stanza disabled: %s", exc)
    _NLP = None

# ────────────────── Config ──────────────────
MAX_TEXT_LENGTH = 30000
MAX_LEMMA_LENGTH = 20000

# ────────────────── helpers ──────────────────
def _lemma(text: str) -> str:
    if _NLP is None:
        return ""
    try:
        if len(text) > MAX_LEMMA_LENGTH:
            logging.debug("_lemma: текст > %d, обрезаем", MAX_LEMMA_LENGTH)
            text = text[:MAX_LEMMA_LENGTH]
        doc = _NLP(text)
        return " ".join(w.lemma or w.text for s in doc.sentences for w in s.words)
    except Exception as e:
        logging.error("Ошибка в лемматизации (Stanza): %s", e)
        return ""

def _norm(text: str) -> str:
    return " ".join(text.split())

def _regex_word(word: str) -> re.Pattern:
    """Точное однословное совпадение с учётом грузинского диапазона."""
    return re.compile(
        rf"(?<![{GE_RANGE}]){re.escape(word)}(?![{GE_RANGE}])",
        re.I,
    )

def _score(kw: str, haystack: str) -> int:
    """Для фраз – fuzz.ratio, для одного слова – regex-совпадение."""
    if " " in kw:
        return fuzz.ratio(kw, haystack)
    return 100 if _regex_word(kw).search(haystack) else 0

def _hits(keywords: List[str], haystack: str, threshold: int) -> Dict[str, int]:
    results = {}
    for kw in keywords:
        score = _score(kw, haystack)
        if score >= threshold:
            results[kw] = score
    return results

# ────────────────── public API ──────────────────
def contains_keywords(text: str, keywords: List[str], *, threshold: int, memory_manager: MemoryManager | None = None) -> bool:
    if not text.strip():
        return False

    if len(text) > MAX_TEXT_LENGTH:
        logging.debug("contains_keywords: текст > %d, обрезаем", MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    if memory_manager and not memory_manager.check_memory():
        logging.warning("MemoryManager: high memory before normalization")
        gc.collect()

    norm = _norm(text)
    if _hits(keywords, norm, threshold):
        gc.collect()
        return True

    lemma = _lemma(norm)
    if memory_manager:
        memory_manager.force_cleanup()
    gc.collect()
    return bool(lemma) and _hits(keywords, lemma, threshold)

def find_keyword_hits(
    text: str,
    keywords: List[str],
    *,
    threshold: int,
    memory_manager: MemoryManager | None = None
) -> Dict[str, int]:
    if not text.strip():
        return {}

    if len(text) > MAX_TEXT_LENGTH:
        logging.debug("find_keyword_hits: текст > %d, обрезаем", MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    norm = _norm(text)
    hits = _hits(keywords, norm, threshold)

    lemma = _lemma(norm)
    gc.collect()
    if lemma:
        hits_lemma = _hits(keywords, lemma, threshold)
        for kw, sc in hits_lemma.items():
            hits[kw] = max(sc, hits.get(kw, 0))
    gc.collect()
    return hits

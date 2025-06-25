from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List

from rapidfuzz import fuzz
import stanza

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
        doc = _NLP(text)  # type: ignore[operator]
        # mypy/pylance: Stanza Document lacks stubs → suppress attr check
        return " ".join(
            w.lemma or w.text  # type: ignore[attr-defined]
            for s in doc.sentences  # type: ignore[attr-defined]
            for w in s.words  # type: ignore[attr-defined]
        )
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
        # RapidFuzz возвращает float; приводим к int для однородности
        return int(fuzz.ratio(kw, haystack))
    return 100 if _regex_word(kw).search(haystack) else 0

def _hits(keywords: List[str], haystack: str, threshold: int) -> Dict[str, int]:
    results = {}
    for kw in keywords:
        score = _score(kw, haystack)
        if score >= threshold:
            results[kw] = score
    return results

# ────────────────── public API ──────────────────
def contains_keywords(text: str, keywords: List[str], *, threshold: int) -> bool:
    if not text.strip():
        return False

    if len(text) > MAX_TEXT_LENGTH:
        logging.debug("contains_keywords: текст > %d, обрезаем", MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    norm = _norm(text)
    if _hits(keywords, norm, threshold):
        return True

    lemma = _lemma(norm)
    if not lemma:
        return False
    return bool(_hits(keywords, lemma, threshold))

def find_keyword_hits(
    text: str,
    keywords: List[str],
    *,
    threshold: int,
) -> Dict[str, int]:
    if not text.strip():
        return {}

    if len(text) > MAX_TEXT_LENGTH:
        logging.debug("find_keyword_hits: текст > %d, обрезаем", MAX_TEXT_LENGTH)
        text = text[:MAX_TEXT_LENGTH]

    norm = _norm(text)
    hits = _hits(keywords, norm, threshold)

    lemma = _lemma(norm)
    if lemma:
        hits_lemma = _hits(keywords, lemma, threshold)
        for kw, sc in hits_lemma.items():
            hits[kw] = max(sc, hits.get(kw, 0))

    return hits

# ge_parser_tenders/text_matcher.py  (целиком)
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


# ────────────────── helpers ──────────────────
def _lemma(text: str) -> str:
    if _NLP is None:
        return ""
    doc = _NLP(text)
    return " ".join(w.lemma or w.text for s in doc.sentences for w in s.words)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _regex_word(word: str) -> re.Pattern:
    """Точное однословное совпадение с учётом грузинского диапазона."""
    return re.compile(
        rf"(?<![{GE_RANGE}]){re.escape(word)}(?![{GE_RANGE}])",
        re.I,
    )


def _score(kw: str, haystack: str) -> int:
    """Строгий scorer: для фраз – fuzz.ratio, для одного слова – regex-совпадение."""
    if " " in kw:                      # фраза ≥ 2 слов
        return fuzz.ratio(kw, haystack)
    return 100 if _regex_word(kw).search(haystack) else 0


def _hits(keywords: List[str], haystack: str, threshold: int) -> Dict[str, int]:
    return {
        kw: _score(kw, haystack)
        for kw in keywords
        if _score(kw, haystack) >= threshold
    }


# ────────────────── public API ──────────────────
def contains_keywords(text: str, keywords: List[str], *, threshold: int) -> bool:
    """True, если найдено ≥ 1 ключа (строгий алгоритм + леммы)."""
    norm = _norm(text)
    if _hits(keywords, norm, threshold):
        return True
    lemma = _lemma(norm)
    return bool(lemma) and _hits(keywords, lemma, threshold)


def find_keyword_hits(
    text: str,
    keywords: List[str],
    *,
    threshold: int,
) -> Dict[str, int]:
    if not text.strip():  # Проверка на пустой текст
        return {}
    """Вернуть dict {keyword: score} — на строгом алгоритме (без partial_ratio)."""
    norm = _norm(text)
    hits = _hits(keywords, norm, threshold)

    lemma = _lemma(norm)
    if lemma:
        hits_lemma = _hits(keywords, lemma, threshold)
        for kw, sc in hits_lemma.items():
            hits[kw] = max(sc, hits.get(kw, 0))
    return hits

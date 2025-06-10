# ge_parser_tenders/text_matcher.py
from __future__ import annotations
from pathlib import Path
import logging
from .text_utils import has_keyword
from rapidfuzz import fuzz
    
import stanza

__all__ = ["contains_keywords"]

# --- инициализация Stanza (однократно) ------------------------------
try:
    _NLP = stanza.Pipeline(
        "ka",
        processors="tokenize,pos,lemma",
        tokenize_no_ssplit=True,
        use_gpu=False,
        logging_level="WARN",
    )
except Exception as exc:           # нет модели — работаем без лемм
    logging.warning("Stanza disabled: %s", exc)
    _NLP = None

# ── Step 0: строгий поиск целых слов ───────────────────────────
if has_keyword(text, keywords):
    return True

def _lemma(text: str) -> str:
    if _NLP is None:
        return ""
    doc = _NLP(text)
    return " ".join((w.lemma or w.text for s in doc.sentences for w in s.words))

def _norm(text: str) -> str:
    return " ".join(text.split())

def _hits(keywords: list[str], haystack: str, threshold: int) -> bool:
    return any(fuzz.partial_ratio(kw, haystack) >= threshold for kw in keywords)

# public ------------------------------------------------------------------
def contains_keywords(text: str, keywords: list[str], *, threshold: int = 80) -> bool:
    """
    True, если хотя бы одно слово из *keywords* встречается в тексте
    с fuzzy-попаданием >= *threshold* (0-100). Сначала прямой текст,
    потом — лемматизация (если включена).
    """
    norm = _norm(text)
    if _hits(keywords, norm, threshold):
        return True
    lemma = _lemma(norm)
    return bool(lemma) and _hits(keywords, lemma, threshold)

def find_keyword_hits(
        text: str,
        keywords: list[str],
        *,
        threshold: int = 90,
        ) -> dict[str, int]:
    
    # norm = _norm(text)
    # direct = {kw: fuzz.partial_ratio(kw, norm)
    #           for kw in keywords
    #           if fuzz.partial_ratio(kw, norm) >= threshold}
    +    from .text_utils import has_keyword
    norm = _norm(text)

    # быстрая строгая проверка
    if not has_keyword(norm, keywords):
        return {}

    direct = {kw: fuzz.partial_ratio(kw, norm)
              for kw in keywords
              if fuzz.partial_ratio(kw, norm) >= threshold}

    lemma = _lemma(norm)
    lemma_hits = {}
    if lemma:
        lemma_hits = {kw: fuzz.partial_ratio(kw, lemma)
                      for kw in keywords
                      if fuzz.partial_ratio(kw, lemma) >= threshold}

    hits = direct.copy()
    for kw, score in lemma_hits.items():
        hits[kw] = max(score, hits.get(kw, 0))
    return hits
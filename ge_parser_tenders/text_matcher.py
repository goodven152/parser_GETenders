# ge_parser_tenders/text_matcher.py
"""
Поиск ключевых слов:
1) strict  (целое грузинское слово) – text_utils.has_keyword
2) fuzzy   (RapidFuzz) – только если strict уже совпал
"""

from rapidfuzz import fuzz
from .text_utils import has_keyword

# ────────────────────────────────────────────────────────────────


def _norm(txt: str) -> str:
    """Простая нормализация для fuzzy-поиска (нижний регистр)."""
    return str(txt).lower()


# --- 1. Строгая проверка -----------------------------------------------------


def contains_keywords(text: str, keywords: list[str]) -> bool:
    """True ↔ в тексте встретилось одно из keywords как целое слово."""
    return has_keyword(text, keywords)


# --- 2. Fuzzy-оценка ---------------------------------------------------------


def find_keyword_hits(
    text: str, keywords: list[str], *, threshold: int = 90
) -> dict[str, int]:
    """
    Возвращает словарь {keyword: score} для тех keyword,
    которые fuzzy-совпали с text не хуже threshold.
    Fuzzy подключается только если строгая проверка прошла.
    """
    if not contains_keywords(text, keywords):
        return {}

    norm = _norm(text)
    return {
        kw: fuzz.partial_ratio(kw, norm)
        for kw in keywords
        if fuzz.partial_ratio(kw, norm) >= threshold
    }

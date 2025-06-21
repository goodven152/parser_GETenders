# parser_getenders/text_utils.py
import re, unicodedata, functools

GE_WORD_BOUND = r"(?:^|[^\u10A0-\u10FF])"          # граница не-грузинской буквы

def normalize(text: str) -> str:
    """NFC + lower + схлопывание пробельных последовательностей."""
    text = unicodedata.normalize("NFC", str(text))
    return " ".join(text.split()).lower()

@functools.lru_cache(maxsize=256)
def _kw_regex(kw: str) -> re.Pattern:
    """Регулярка «целое грузинское слово kw»."""
    return re.compile(f"{GE_WORD_BOUND}{re.escape(kw)}{GE_WORD_BOUND}", re.I)

def has_keyword(text: str, keywords: list[str]) -> bool:
    nt = normalize(text)
    return any(_kw_regex(kw).search(nt) for kw in keywords)

from pathlib import Path
from datetime import datetime
from pydantic_settings import BaseSettings
from pydantic import HttpUrl, Field
from typing import Optional

class ParserSettings(BaseSettings):
    start_url:  HttpUrl = Field(..., alias="START_URL")
    page_rows:  int     = Field(4,  alias="PAGE_ROWS")
    fuzzy_threshold: int = Field(85, alias="FUZZY_THRESHOLD")
    use_stanza_lemmas: bool = Field(True, alias="USE_STANZA_LEMMAS")
    keywords_geo: list[str] = Field(..., alias="KEYWORDS_GEO")
    excluded_firm: str = Field(..., alias="EXCLUDED_FIRM")
    output: str = "found_tenders.json"
    max_pages: Optional[int] = None          # None → все страницы
    headless: bool = True                    # True = headless Chrome
    reset_cache: bool = False
    log: str = "INFO"
    started_at: datetime | None = None
    model_config = {"extra": "ignore"}

    @classmethod
    def load(cls, path: str | Path = "config.json") -> "ParserSettings":
        from pathlib import Path
        return cls.model_validate_json(Path(path).read_bytes())

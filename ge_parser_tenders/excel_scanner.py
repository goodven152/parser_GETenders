from pathlib import Path
import pandas as pd
from config import settings
from .text_utils import has_keyword, normalize

attachment_bad = False

for row_idx, row in df.iterrows():
    for col in df.columns:
        cell = row[col]
        if has_keyword(cell, settings.forbidden_words):
            attachment_bad = True
            logger.warning(
                "⚠️  keyword «%s» -> файл %s, лист «%s», ячейка %s%d",
                cell, file_path.name, sheet_name, col, row_idx + 2  # +1 за header
            )
            break      # прерываемся – одного совпадения достаточно
    if attachment_bad:
        break
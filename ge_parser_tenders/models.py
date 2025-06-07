# models.py (пример)
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel

GEORGIA_TZ = timezone(timedelta(hours=4))

class Run(BaseModel):
    id: int
    started_at: datetime      # tz-aware!

    @staticmethod
    def from_row(row):
        # row.started_at хранится как naive-UTC в БД
        ts = row.started_at.replace(tzinfo=timezone.utc).astimezone(GEORGIA_TZ)
        return Run(id=row.id, started_at=ts)

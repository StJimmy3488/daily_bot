from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bot.clock import parse_hhmm
from bot.db.models import Setting

DEFAULTS = {
    "morning": "08:00",
    "evening": "21:00",
    "quiet": "22:00-08:00",  # or "off"
    "focus_until": "",  # ISO UTC timestamp
    "work_hours": "09:00-18:00",  # the smart plan fills free time inside this window
    "google_refresh_token": "",
    "google_oauth_state": "",  # "<state>|<ISO expiry>" while a connect link is open
}


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now < end
    return now >= start or now < end  # window wraps past midnight


class SettingsStore:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> str:
        row = await self.session.get(Setting, key)
        return row.value if row else DEFAULTS[key]

    async def set(self, key: str, value: str) -> None:
        await self.session.merge(Setting(key=key, value=value))

    async def get_time(self, key: str) -> time:
        return parse_hhmm(await self.get(key))

    async def focus_until(self) -> datetime | None:
        value = await self.get("focus_until")
        return datetime.fromisoformat(value) if value else None

    async def work_hours(self) -> tuple[time, time]:
        start, end = (parse_hhmm(part) for part in (await self.get("work_hours")).split("-"))
        return start, end

    async def is_muted(self, now: datetime, tz: ZoneInfo) -> bool:
        """Task reminders: muted by focus mode and quiet hours."""
        focus = await self.focus_until()
        if focus and now < focus:
            return True
        return await self.is_quiet(now, tz)

    async def is_quiet(self, now: datetime, tz: ZoneInfo) -> bool:
        """Meeting heads-ups respect quiet hours only — focus shouldn't make you miss a meeting."""
        quiet = await self.get("quiet")
        if quiet == "off":
            return False
        start, end = (parse_hhmm(part) for part in quiet.split("-"))
        return in_quiet_hours(now.astimezone(tz).time(), start, end)

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def as_utc(dt: datetime) -> datetime:
    """Normalise to aware UTC (values built in code may be naive or in another zone)."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def local_to_utc(d: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC)


def day_bounds_utc(d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return local_to_utc(d, time(0), tz), local_to_utc(d + timedelta(days=1), time(0), tz)


def parse_hhmm(value: str) -> time:
    hours, minutes = value.strip().split(":")
    return time(int(hours), int(minutes))

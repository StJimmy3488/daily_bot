"""Mirror Google Calendar into calendar_events for a rolling window."""

import logging
from datetime import date, datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.clock import as_utc, local_to_utc, local_today
from bot.db.models import CalendarEvent
from bot.google_calendar import GoogleCalendar

log = logging.getLogger(__name__)

PAST_DAYS = 1
FUTURE_DAYS = 14


def parse_event(item: dict, tz: ZoneInfo) -> dict | None:
    """Google event resource -> CalendarEvent fields, or None if it should be ignored."""
    if item.get("status") == "cancelled":
        return None
    if any(a.get("self") and a.get("responseStatus") == "declined" for a in item.get("attendees", [])):
        return None
    start, end = item.get("start", {}), item.get("end", {})
    if "dateTime" in start:
        start_at = as_utc(datetime.fromisoformat(start["dateTime"]))
        end_at = as_utc(datetime.fromisoformat(end["dateTime"]))
        all_day = False
    elif "date" in start:
        start_at = local_to_utc(date.fromisoformat(start["date"]), time(0), tz)
        end_at = local_to_utc(date.fromisoformat(end["date"]), time(0), tz)  # exclusive
        all_day = True
    else:
        return None

    video = next(
        (
            e.get("uri")
            for e in item.get("conferenceData", {}).get("entryPoints", [])
            if e.get("entryPointType") == "video"
        ),
        None,
    )
    return {
        "title": item.get("summary") or "(no title)",
        "start_at": start_at,
        "end_at": end_at,
        "all_day": all_day,
        "busy": item.get("transparency") != "transparent",
        "link": item.get("hangoutLink") or video or item.get("htmlLink"),
    }


async def sync_calendar(session: AsyncSession, gcal: GoogleCalendar, refresh_token: str, tz: ZoneInfo) -> int:
    """Upsert every event in the window and delete the ones that disappeared. Returns the event count."""
    today = local_today(tz)
    window_start = local_to_utc(today - timedelta(days=PAST_DAYS), time(0), tz)
    window_end = local_to_utc(today + timedelta(days=FUTURE_DAYS), time(0), tz)

    fetched: dict[tuple[str, str], dict] = {}
    for cal in await gcal.list_calendars(refresh_token):
        if not (cal.get("selected") or cal.get("primary")):
            continue
        for item in await gcal.list_events(refresh_token, quote(cal["id"], safe=""), window_start, window_end):
            if fields := parse_event(item, tz):
                fetched[(cal["id"], item["id"])] = fields

    existing = {
        (e.calendar_id, e.event_id): e
        for e in await session.scalars(
            select(CalendarEvent).where(CalendarEvent.start_at < window_end, CalendarEvent.end_at > window_start)
        )
    }
    for key, fields in fetched.items():
        event = existing.pop(key, None)
        if event is None:
            session.add(CalendarEvent(calendar_id=key[0], event_id=key[1], **fields))
            continue
        if as_utc(event.start_at) != fields["start_at"]:
            event.notified_at = None  # moved: ping again
        for name, value in fields.items():
            setattr(event, name, value)
    for gone in existing.values():
        await session.delete(gone)
    await session.execute(delete(CalendarEvent).where(CalendarEvent.end_at <= window_start))

    log.info("Calendar sync: %d event(s)", len(fetched))
    return len(fetched)

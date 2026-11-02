"""Change or delete Google Calendar events; shared by the Mini App and the chat.

Google is changed first, then the local mirror row, so the app shows the result
right away instead of after the next 15-minute sync.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bot.calendar_sync import parse_event
from bot.clock import as_utc
from bot.db.models import CalendarEvent
from bot.google_calendar import CalendarAuthError, CalendarError, GoogleCalendar


class EventEditError(Exception):
    """A user-facing reason the change couldn't be made."""


@dataclass
class EventChange:
    title: str | None = None
    start: datetime | None = None  # local, timed events
    end: datetime | None = None
    day: date | None = None  # all-day events: move to this day, keeping their length


def _google_body(event: CalendarEvent, change: EventChange, tz: ZoneInfo) -> dict:
    body: dict = {}
    if change.title is not None:
        body["summary"] = change.title
    if event.all_day:
        if change.day is not None:
            length = as_utc(event.end_at) - as_utc(event.start_at)
            days = max(1, round(length / timedelta(days=1)))
            body["start"] = {"date": change.day.isoformat()}
            body["end"] = {"date": (change.day + timedelta(days=days)).isoformat()}
    elif change.start is not None or change.end is not None:
        start = change.start or as_utc(event.start_at).astimezone(tz)
        # Moving the start keeps the duration unless a new end is given.
        end = change.end or start + (as_utc(event.end_at) - as_utc(event.start_at))
        if end <= start:
            raise EventEditError("The event has to end after it starts")
        body["start"] = {"dateTime": start.isoformat(), "timeZone": str(tz)}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": str(tz)}
    return body


def _explain(e: CalendarError) -> EventEditError:
    if e.status == 403:
        return EventEditError("Google doesn't allow changing this event (you're probably a guest)")
    if e.status in (404, 410):
        return EventEditError("This event no longer exists in Google Calendar")
    return EventEditError("Google Calendar didn't accept the change, try again later")


async def update_event(
    session: AsyncSession, gcal: GoogleCalendar, token: str, event: CalendarEvent, change: EventChange, tz: ZoneInfo
) -> CalendarEvent:
    if not event.editable:
        raise EventEditError("Only the organizer can change this event")
    body = _google_body(event, change, tz)
    if not body:
        return event
    try:
        updated = await gcal.patch_event(token, event.calendar_id, event.event_id, body)
    except CalendarAuthError as e:
        raise EventEditError("Google Calendar access expired — reconnect with /calendar") from e
    except CalendarError as e:
        raise _explain(e) from e

    fields = parse_event(updated, tz)
    if fields is not None:
        old_start = as_utc(event.start_at)
        for name in ("title", "start_at", "end_at", "all_day", "link"):
            setattr(event, name, fields[name])
        if fields["start_at"] != old_start:
            event.notified_at = None  # moved: ping again before the new time
    await session.flush()
    return event


async def delete_event(session: AsyncSession, gcal: GoogleCalendar, token: str, event: CalendarEvent) -> None:
    if not event.editable:
        raise EventEditError("Only the organizer can delete this event")
    try:
        await gcal.delete_event(token, event.calendar_id, event.event_id)
    except CalendarAuthError as e:
        raise EventEditError("Google Calendar access expired — reconnect with /calendar") from e
    except CalendarError as e:
        raise _explain(e) from e
    await session.delete(event)
    await session.flush()

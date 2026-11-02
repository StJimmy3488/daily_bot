from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.actions import describe, event_change
from bot.assistant import EventDeleteAction, EventUpdateAction, action_from_tool, build_context
from bot.calendar_edit import EventChange, EventEditError, delete_event, update_event
from bot.calendar_sync import can_edit, parse_event
from bot.clock import as_utc
from bot.db.models import CalendarEvent
from bot.dev_init_data import sign_init_data
from bot.google_calendar import CalendarError, GoogleCalendar
from bot.web import create_app
from tests.conftest import TZ

DAY = date(2026, 11, 2)


def local(h, m=0, day=DAY):
    return datetime.combine(day, time(h, m), tzinfo=TZ)


# --- who may edit ---

ME = {"email": "me@x", "self": True}
BOSS = {"email": "boss@x"}


@pytest.mark.parametrize(
    ("item", "role", "editable"),
    [
        ({}, "owner", True),  # my own event, no guests
        ({"attendees": [{**ME, "organizer": True}, BOSS]}, "owner", True),  # I organize
        ({"attendees": [ME, {**BOSS, "organizer": True}]}, "owner", False),  # I'm invited
        ({"attendees": [ME, BOSS], "guestsCanModify": True}, "owner", True),
        ({}, "writer", True),  # shared team calendar I can write to
        ({}, "reader", False),
        ({"eventType": "birthday"}, "owner", False),
    ],
)
def test_can_edit(item, role, editable):
    assert can_edit(item, role) is editable


def test_parse_event_flags():
    item = {
        "summary": "Weekly sync",
        "start": {"dateTime": "2026-11-02T10:00:00+02:00"},
        "end": {"dateTime": "2026-11-02T10:30:00+02:00"},
        "recurringEventId": "abc",
        "attendees": [{**ME, "organizer": True}, BOSS],
    }
    fields = parse_event(item, TZ, "owner")
    assert fields["editable"] and fields["recurring"] and fields["has_guests"]
    assert not parse_event({**item, "attendees": [ME]}, TZ)["has_guests"]


# --- changing events ---


class FakeGcal:
    def __init__(self, fail_status: int | None = None):
        self.calls = []
        self.fail_status = fail_status

    async def patch_event(self, token, calendar_id, event_id, changes):
        self.calls.append(("patch", calendar_id, event_id, changes))
        if self.fail_status:
            raise CalendarError("nope", self.fail_status)
        item = {"summary": changes.get("summary", "Design review"), "htmlLink": "https://cal/x"}
        item["start"] = changes.get("start", {"dateTime": local(11).isoformat()})
        item["end"] = changes.get("end", {"dateTime": local(12).isoformat()})
        return item

    async def delete_event(self, token, calendar_id, event_id):
        self.calls.append(("delete", calendar_id, event_id))
        if self.fail_status:
            raise CalendarError("nope", self.fail_status)


async def add_event(session, title="Design review", start=None, end=None, all_day=False, editable=True, **kw):
    e = CalendarEvent(
        calendar_id="primary",
        event_id=f"ev-{title}",
        title=title,
        start_at=start or local(11),
        end_at=end or local(12),
        all_day=all_day,
        editable=editable,
        notified_at=datetime.now(UTC),
        **kw,
    )
    session.add(e)
    await session.flush()
    return e


async def test_move_keeps_duration_and_updates_mirror(session):
    event = await add_event(session)
    gcal = FakeGcal()

    await update_event(session, gcal, "tok", event, EventChange(start=local(15)), TZ)

    _, cal, ev_id, body = gcal.calls[0]
    assert (cal, ev_id) == ("primary", "ev-Design review")
    assert body["start"] == {"dateTime": local(15).isoformat(), "timeZone": "Europe/Riga"}
    assert body["end"]["dateTime"] == local(16).isoformat()  # still one hour
    assert as_utc(event.start_at) == local(15).astimezone(UTC)  # local copy updated right away
    assert event.notified_at is None  # moved: heads-up again


async def test_rename_and_resize(session):
    event = await add_event(session)
    gcal = FakeGcal()
    await update_event(session, gcal, "tok", event, EventChange(title="Design review v2", end=local(11, 30)), TZ)
    body = gcal.calls[0][3]
    assert body["summary"] == "Design review v2"
    assert (body["start"]["dateTime"], body["end"]["dateTime"]) == (local(11).isoformat(), local(11, 30).isoformat())
    assert event.title == "Design review v2"


async def test_all_day_move_keeps_length(session):
    trip = await add_event(
        session, "Trip", start=local(0, day=DAY), end=local(0, day=DAY + timedelta(days=3)), all_day=True
    )
    gcal = FakeGcal()
    await update_event(session, gcal, "tok", trip, EventChange(day=date(2026, 11, 10)), TZ)
    assert gcal.calls[0][3] == {"start": {"date": "2026-11-10"}, "end": {"date": "2026-11-13"}}


async def test_refusals(session):
    guest = await add_event(session, "Board meeting", editable=False)
    with pytest.raises(EventEditError, match="organizer"):
        await update_event(session, FakeGcal(), "tok", guest, EventChange(title="x"), TZ)
    with pytest.raises(EventEditError, match="organizer"):
        await delete_event(session, FakeGcal(), "tok", guest)

    mine = await add_event(session)
    with pytest.raises(EventEditError, match="end after"):
        await update_event(session, FakeGcal(), "tok", mine, EventChange(start=local(13), end=local(12)), TZ)
    with pytest.raises(EventEditError, match="guest"):
        await update_event(session, FakeGcal(fail_status=403), "tok", mine, EventChange(title="x"), TZ)
    assert mine.title == "Design review"  # nothing changed locally when Google refused


async def test_delete(session):
    event = await add_event(session)
    gcal = FakeGcal()
    await delete_event(session, gcal, "tok", event)
    assert gcal.calls == [("delete", "primary", "ev-Design review")]
    assert (await session.scalars(select(CalendarEvent))).all() == []


async def test_google_client_treats_gone_as_deleted(monkeypatch):
    gcal = GoogleCalendar("id", "secret", "https://x")
    seen = {}

    async def fake_request(token, method, path, **kw):
        seen["path"] = path
        raise CalendarError("gone", 410)

    monkeypatch.setattr(gcal, "_request", fake_request)
    await gcal.delete_event("tok", "team#x@group.calendar.google.com", "abc_20261102T090000Z")  # no exception
    assert seen["path"] == "/calendars/team%23x%40group.calendar.google.com/events/abc_20261102T090000Z"


# --- chat ---


def test_tool_parsing():
    a = action_from_tool("update_calendar_event", {"id": 7, "title": "", "date": "", "start": "15:00", "minutes": 0})
    assert a == EventUpdateAction(event_id=7, start=time(15))
    assert action_from_tool("delete_calendar_event", {"id": 7}) == EventDeleteAction(event_id=7)
    with pytest.raises(ValueError):
        action_from_tool("update_calendar_event", {"id": 7, "title": "", "date": "fri", "start": "", "minutes": 0})


async def test_event_change_from_chat(session):
    event = await add_event(session)  # Mon 11:00-12:00
    fri = date(2026, 11, 6)
    assert event_change(EventUpdateAction(event_id=event.id, day=fri), event, TZ) == EventChange(
        start=local(11, day=fri)
    )
    assert event_change(EventUpdateAction(event_id=event.id, start=time(15), minutes=30), event, TZ) == EventChange(
        start=local(15), end=local(15, 30)
    )
    assert event_change(EventUpdateAction(event_id=event.id, minutes=90), event, TZ) == EventChange(end=local(12, 30))

    labels = {event.id: event}
    assert describe(EventUpdateAction(event_id=event.id, start=time(15)), {}, DAY, labels) == (
        "📅✏️ Design review: → 15:00"
    )
    assert describe(EventDeleteAction(event_id=event.id), {}, DAY, labels) == "📅🗑 Cancel “Design review”"


async def test_context_lists_event_ids_and_guest_marker(session):
    mine = await add_event(session)
    guest = await add_event(session, "Board meeting", start=local(14), end=local(15), editable=False)
    ctx = build_context([], local(9), None, [mine, guest])
    assert f"{mine.id} | Mon 2026-11-02 11:00-12:00 | Design review" in ctx
    assert f"{guest.id} | Mon 2026-11-02 14:00-15:00 | Board meeting (guest)" in ctx


# --- API ---

TOKEN, OWNER = "123:T", 99


@pytest.fixture
async def api(session, store):
    gcal = FakeGcal()
    maker = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    app = create_app(None, maker, OWNER, gcal, None, bot_token=TOKEN, tz=TZ, assistant=None)
    headers = {"Authorization": f"tma {sign_init_data(TOKEN, OWNER)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        c.gcal = gcal
        yield c


async def test_api_edit_and_delete(api, session, store):
    event = await add_event(session, has_guests=True)
    assert (await api.patch(f"/api/events/{event.id}", json={"title": "x"})).status_code == 409  # not connected

    await store.set("google_refresh_token", "tok")
    await session.flush()  # make it visible to the API's own session
    r = await api.patch(f"/api/events/{event.id}", json={"start": "2026-11-02T14:00"})
    assert r.status_code == 200
    assert (r.json()["start"], r.json()["end"]) == ("2026-11-02T14:00", "2026-11-02T15:00")
    assert r.json()["editable"] and r.json()["has_guests"]

    guest = await add_event(session, "Board meeting", editable=False)
    r = await api.patch(f"/api/events/{guest.id}", json={"title": "x"})
    assert r.status_code == 409 and "organizer" in r.json()["detail"]

    assert (await api.delete(f"/api/events/{event.id}")).status_code == 204
    assert (await api.delete(f"/api/events/{event.id}")).status_code == 404

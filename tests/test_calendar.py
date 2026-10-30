from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from sqlalchemy import select

from bot.calendar_sync import parse_event, sync_calendar
from bot.clock import as_utc, local_today
from bot.db.models import CalendarEvent, TaskStatus
from bot.recurrence import describe_rule, first_occurrence, next_occurrence, normalize_rule
from bot.smart_plan import fit_day
from bot.web import check_oauth_state, new_oauth_state
from tests.conftest import TZ

DAY = date(2026, 10, 29)  # Thursday


# --- recurrence ---


@pytest.mark.parametrize(
    ("rule", "due", "today", "expected"),
    [
        ("FREQ=WEEKLY;BYDAY=MO", date(2026, 10, 26), date(2026, 10, 26), date(2026, 11, 2)),  # on time
        ("FREQ=WEEKLY;BYDAY=MO", date(2026, 10, 26), date(2026, 10, 28), date(2026, 11, 2)),  # late
        ("FREQ=WEEKLY;BYDAY=MO", date(2026, 11, 2), date(2026, 10, 31), date(2026, 11, 9)),  # early
        ("FREQ=DAILY", date(2026, 10, 20), date(2026, 10, 29), date(2026, 10, 30)),
        ("FREQ=MONTHLY;BYMONTHDAY=1", date(2026, 11, 1), date(2026, 11, 1), date(2026, 12, 1)),
    ],
)
def test_next_occurrence(rule, due, today, expected):
    assert next_occurrence(rule, due, today) == expected


def test_rule_helpers():
    assert normalize_rule(" rrule:freq=weekly;byday=mo ") == "FREQ=WEEKLY;BYDAY=MO"
    for bad in ["every monday", "FREQ=SOMETIMES", "DTSTART:20260101T000000\nFREQ=DAILY"]:
        with pytest.raises(ValueError):
            normalize_rule(bad)
    assert first_occurrence("FREQ=WEEKLY;BYDAY=MO", DAY) == date(2026, 11, 2)
    assert describe_rule("FREQ=WEEKLY;BYDAY=MO") == "weekly on mo"


async def test_completing_recurring_task_spawns_next(repo):
    today = local_today(TZ)
    task = await repo.create("Water plants", due_date=today, due_time=time(9), recurrence_rule="FREQ=DAILY")
    nxt = await repo.complete(task)
    assert nxt.title == "Water plants" and nxt.due_date == today + timedelta(days=1) and nxt.due_time == time(9)
    assert nxt.status == TaskStatus.TODO and nxt.recurrence_rule == "FREQ=DAILY"

    one_off = await repo.create("Once", due_date=today)
    assert await repo.complete(one_off) is None


# --- google events ---


def test_parse_event_variants():
    timed = parse_event(
        {
            "summary": "Standup",
            "start": {"dateTime": "2026-10-29T10:00:00+02:00"},
            "end": {"dateTime": "2026-10-29T10:15:00+02:00"},
            "hangoutLink": "https://meet.google.com/abc",
        },
        TZ,
    )
    assert timed["start_at"] == datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
    assert not timed["all_day"] and timed["busy"] and timed["link"] == "https://meet.google.com/abc"

    all_day = parse_event({"summary": "Trip", "start": {"date": "2026-10-29"}, "end": {"date": "2026-10-30"}}, TZ)
    assert all_day["all_day"] and all_day["start_at"] == datetime(2026, 10, 28, 22, 0, tzinfo=UTC)

    free = parse_event({"start": {"dateTime": "2026-10-29T10:00:00Z"}, "end": {"dateTime": "2026-10-29T11:00:00Z"}, "transparency": "transparent"}, TZ)
    assert free["busy"] is False and free["title"] == "(no title)"

    assert parse_event({"status": "cancelled"}, TZ) is None
    declined = {"start": {"dateTime": "2026-10-29T10:00:00Z"}, "end": {"dateTime": "2026-10-29T11:00:00Z"}, "attendees": [{"self": True, "responseStatus": "declined"}]}
    assert parse_event(declined, TZ) is None


class FakeGcal:
    def __init__(self, events_by_cal):
        self.events_by_cal = events_by_cal

    async def list_calendars(self, token):
        return [{"id": "primary@x", "primary": True}, {"id": "hidden", "selected": False}, {"id": "work", "selected": True}]

    async def list_events(self, token, calendar_id, start, end):
        return self.events_by_cal.get(unquote(calendar_id), [])  # ids arrive URL-encoded


def _event(event_id, start: datetime, minutes=30, title="Meeting"):
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
    }


async def test_sync_upserts_and_deletes(session):
    soon = datetime.now(TZ).replace(microsecond=0) + timedelta(hours=2)
    gcal = FakeGcal({"primary@x": [_event("a", soon), _event("b", soon)], "work": [_event("c", soon)], "hidden": [_event("h", soon)]})
    assert await sync_calendar(session, gcal, "token", TZ) == 3
    await session.flush()

    a = (await session.scalars(select(CalendarEvent).where(CalendarEvent.event_id == "a"))).one()
    a.notified_at = datetime.now(UTC)
    gcal.events_by_cal = {"primary@x": [_event("a", soon + timedelta(hours=1), title="Moved")], "work": [_event("c", soon)]}
    assert await sync_calendar(session, gcal, "token", TZ) == 2
    await session.flush()

    rows = {e.event_id: e for e in await session.scalars(select(CalendarEvent))}
    assert set(rows) == {"a", "c"}
    assert rows["a"].title == "Moved" and rows["a"].notified_at is None  # moved -> ping again
    assert as_utc(rows["a"].start_at) == (soon + timedelta(hours=1)).astimezone(UTC)


# --- smart plan fitting ---


def _task(id, title, minutes=None, due_time=None):
    return SimpleNamespace(id=id, title=title, est_minutes=minutes, due_time=due_time, due_date=DAY, priority=2)


def _meeting(start: time, end: time, busy=True, all_day=False):
    return SimpleNamespace(
        title="Meeting",
        start_at=datetime.combine(DAY, start, tzinfo=TZ),
        end_at=datetime.combine(DAY, end, tzinfo=TZ),
        busy=busy,
        all_day=all_day,
    )


def test_fit_day_never_overlaps_meetings():
    early = datetime.combine(DAY, time(7), tzinfo=TZ)
    tasks = [_task(1, "Long", 90), _task(2, "Short", 20), _task(3, "Huge", 600), _task(4, "Call", due_time=time(13))]
    events = [_meeting(time(10), time(11)), _meeting(time(11, 30), time(12)), _meeting(time(9), time(17), busy=False)]

    plan = fit_day(DAY, tasks, {}, events, (time(9), time(18)), TZ, early)

    placed = {b.task.id: (b.start.time(), b.end.time()) for b in plan.blocks if b.task}
    # 90 min doesn't fit before 10:00, between the meetings or before the 13:00 call
    assert placed[1] == (time(13, 15), time(14, 45))
    assert placed[2] == (time(9), time(9, 20))  # first gap that fits 20 min
    assert placed[4] == (time(13), time(13, 15))  # fixed-time task stays put
    assert [t.id for t in plan.unplaced] == [3]
    busy = sorted((b.start, b.end) for b in plan.blocks)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(busy, busy[1:]))  # no overlaps at all


def test_fit_day_starts_from_now_today():
    now = datetime.combine(DAY, time(14, 3), tzinfo=TZ)
    plan = fit_day(DAY, [_task(1, "A", 30)], {}, [], (time(9), time(18)), TZ, now)
    assert plan.blocks[0].start.time() == time(14, 5)


# --- oauth state ---


async def test_oauth_state(store):
    state = await new_oauth_state(store)
    assert await check_oauth_state(store, state)
    assert not await check_oauth_state(store, state + "x")
    await store.set("google_oauth_state", f"{state}|{(datetime.now(UTC) - timedelta(minutes=1)).isoformat()}")
    assert not await check_oauth_state(store, state)

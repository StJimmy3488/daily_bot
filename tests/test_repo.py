from datetime import date, time, timedelta

from sqlalchemy import select

from bot.clock import as_utc, local_to_utc, local_today
from bot.db.models import Event, Reminder, TaskStatus
from tests.conftest import TZ

TODAY = date(2026, 10, 29)


async def test_today_inbox_and_events(session, repo):
    overdue = await repo.create("overdue", due_date=TODAY - timedelta(days=2))
    low = await repo.create("low today", priority=3, due_date=TODAY)
    high = await repo.create("high today", priority=1, due_date=TODAY)
    await repo.create("later", due_date=TODAY + timedelta(days=3))
    inbox = await repo.create("inbox item")

    assert [t.id for t in await repo.list_today(TODAY)] == [overdue.id, high.id, low.id]
    assert [t.id for t in await repo.list_inbox()] == [inbox.id]

    await repo.complete(high)
    await repo.reschedule(inbox, TODAY)
    await repo.drop(low)
    await session.flush()

    assert [t.id for t in await repo.list_today(TODAY)] == [overdue.id, inbox.id]
    assert high.status == TaskStatus.DONE and high.done_at is not None
    actions = list(await session.scalars(select(Event.action).where(Event.task_id == inbox.id)))
    assert actions == ["created", "moved"]


async def pending(session, task_id):
    stmt = select(Reminder).where(Reminder.task_id == task_id, Reminder.sent_at.is_(None))
    return list(await session.scalars(stmt))


async def test_reminder_follows_task(session, repo):
    tomorrow = local_today(TZ) + timedelta(days=1)
    task = await repo.create("dentist", due_date=tomorrow, due_time=time(14, 30))
    [r] = await pending(session, task.id)
    assert as_utc(r.fire_at) == local_to_utc(tomorrow, time(14, 30), TZ)

    await repo.reschedule(task, tomorrow + timedelta(days=1))
    [r] = await pending(session, task.id)
    assert as_utc(r.fire_at) == local_to_utc(tomorrow + timedelta(days=1), time(14, 30), TZ)

    await repo.complete(task)
    assert await pending(session, task.id) == []


async def test_no_reminder_without_time_or_in_past(session, repo):
    no_time = await repo.create("no time", due_date=local_today(TZ) + timedelta(days=1))
    past = await repo.create("past", due_date=local_today(TZ) - timedelta(days=1), due_time=time(9, 0))
    assert await pending(session, no_time.id) == []
    assert await pending(session, past.id) == []


async def test_snooze_and_due_reminders(session, repo):
    task = await repo.create("call", due_date=local_today(TZ) + timedelta(days=1), due_time=time(9, 0))
    await repo.snooze(task, -1)  # already due
    await session.flush()
    due = await repo.due_reminders()
    assert [t.id for _, t in due] == [task.id]
    assert len(await pending(session, task.id)) == 1  # snooze replaced the scheduled one


async def test_rollover(session, repo):
    old = await repo.create("old", due_date=TODAY - timedelta(days=2))
    done = await repo.create("done", due_date=TODAY - timedelta(days=1))
    await repo.complete(done)
    inbox = await repo.create("inbox")

    assert await repo.rollover(TODAY) == 1
    assert old.due_date == TODAY
    assert done.due_date == TODAY - timedelta(days=1)
    assert inbox.due_date is None
    await session.flush()
    slips = list(await session.scalars(select(Event).where(Event.action == "slipped")))
    assert [e.task_id for e in slips] == [old.id]


async def test_get_many_keeps_order(repo):
    a, b, c = [await repo.create(n) for n in "abc"]
    assert [t.id for t in await repo.get_many([c.id, a.id, 999, b.id])] == [c.id, a.id, b.id]

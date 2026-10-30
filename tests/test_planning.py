from datetime import UTC, date, datetime, time, timedelta

import pytest

from bot.db.models import TaskStatus
from bot.planning import accept_plan, day_summary_if_closed
from bot.settings_store import in_quiet_hours
from tests.conftest import TZ

TODAY = date(2026, 10, 29)


@pytest.mark.parametrize(
    ("now", "start", "end", "quiet"),
    [
        (time(23, 0), time(22, 0), time(8, 0), True),
        (time(7, 59), time(22, 0), time(8, 0), True),
        (time(8, 0), time(22, 0), time(8, 0), False),
        (time(13, 0), time(12, 0), time(14, 0), True),
        (time(15, 0), time(12, 0), time(14, 0), False),
    ],
)
def test_in_quiet_hours(now, start, end, quiet):
    assert in_quiet_hours(now, start, end) is quiet


async def test_is_muted_by_focus_and_quiet(store):
    noon = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)  # 12:00 in Riga
    assert not await store.is_muted(noon, TZ)
    await store.set("focus_until", (noon + timedelta(minutes=30)).isoformat())
    assert await store.is_muted(noon, TZ)
    assert not await store.is_muted(noon + timedelta(hours=1), TZ)
    await store.set("quiet", "11:00-13:00")
    assert await store.is_muted(noon + timedelta(hours=1), TZ) is False  # 13:00 local, window ended
    assert await store.is_muted(noon - timedelta(minutes=30), TZ)


async def test_accept_plan_pulls_chosen_and_pushes_skipped(repo):
    overdue = await repo.create("overdue", due_date=TODAY - timedelta(days=1))
    skipped = await repo.create("skip me", due_date=TODAY)
    inbox = await repo.create("from inbox")
    inbox_skipped = await repo.create("stay in inbox")
    proposed = [overdue.id, skipped.id, inbox.id, inbox_skipped.id]

    plan = await repo.save_plan(TODAY, [overdue.id, inbox.id])
    chosen = await accept_plan(repo, plan, proposed, TODAY)

    assert [t.id for t in chosen] == [overdue.id, inbox.id]
    assert overdue.due_date == TODAY and inbox.due_date == TODAY
    assert skipped.due_date == TODAY + timedelta(days=1)
    assert inbox_skipped.due_date is None
    assert plan.accepted_at is not None


async def test_day_summary_after_review(repo):
    a = await repo.create("a", due_date=TODAY)
    b = await repo.create("b", due_date=TODAY)
    plan = await repo.save_plan(TODAY, [a.id, b.id])
    await repo.complete(a)
    assert await day_summary_if_closed(repo, a, TODAY) is None  # review not started

    plan.reviewed_at = datetime.now(UTC)
    assert await day_summary_if_closed(repo, a, TODAY) is None  # b still open
    await repo.reschedule(b, TODAY + timedelta(days=1))
    assert await day_summary_if_closed(repo, b, TODAY) == "🌙 Day closed — 1/2 done"
    assert b.status == TaskStatus.TODO

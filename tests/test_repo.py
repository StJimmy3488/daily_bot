from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from bot.db.models import Base, Event, TaskStatus
from bot.db.session import make_sessionmaker
from bot.repo import TaskRepo

TODAY = date(2026, 10, 29)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with make_sessionmaker(engine)() as s:
        yield s
    await engine.dispose()


async def test_today_inbox_and_events(session):
    repo = TaskRepo(session)
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

"""Tests run against real Postgres (TEST_DATABASE_URL), like production.

The schema is created once per run; every test works inside a transaction that
is rolled back afterwards, so tests are isolated and fast.
"""

import asyncio
import os
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from bot.db.models import Base
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore

TZ = ZoneInfo("Europe/Riga")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://planner:planner@localhost:5432/planner_test"
)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    async def reset() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(reset())


@pytest.fixture
async def session():
    # NullPool + an engine per test: asyncpg connections are bound to the test's event loop.
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        s = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            await s.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
def repo(session):
    return TaskRepo(session, TZ)


@pytest.fixture
def store(session):
    return SettingsStore(session)

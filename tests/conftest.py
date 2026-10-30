from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from bot.db.models import Base
from bot.db.session import make_sessionmaker
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore

TZ = ZoneInfo("Europe/Riga")


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with make_sessionmaker(engine)() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def repo(session):
    return TaskRepo(session, TZ)


@pytest.fixture
def store(session):
    return SettingsStore(session)

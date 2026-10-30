from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.clock import local_today
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class WhitelistMiddleware(BaseMiddleware):
    """Silently drop every update that isn't from the owner."""

    def __init__(self, owner_id: int):
        self.owner_id = owner_id

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.id != self.owner_id:
            return None
        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    """One transaction per update; handlers get `repo` and the owner's local `today`."""

    def __init__(self, sessionmaker: async_sessionmaker, tz: ZoneInfo):
        self.sessionmaker = sessionmaker
        self.tz = tz

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self.sessionmaker() as session, session.begin():
            data["repo"] = TaskRepo(session, self.tz)
            data["store"] = SettingsStore(session)
            data["today"] = local_today(self.tz)
            return await handler(event, data)

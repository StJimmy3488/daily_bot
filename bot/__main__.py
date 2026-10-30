import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.db.session import make_engine, make_sessionmaker
from bot.handlers import build_router
from bot.handlers.common import COMMANDS
from bot.middlewares import DbSessionMiddleware, WhitelistMiddleware
from bot.scheduler import PlannerScheduler


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    engine = make_engine(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sessionmaker = make_sessionmaker(engine)
    # In a private chat the chat id equals the user id.
    scheduler = PlannerScheduler(bot, sessionmaker, chat_id=settings.owner_id, tz=settings.tz)
    dp = Dispatcher(scheduler=scheduler)

    dp.update.outer_middleware(WhitelistMiddleware(settings.owner_id))
    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker, settings.tz))
    dp.include_router(build_router())

    await bot.set_my_commands(COMMANDS)
    await scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

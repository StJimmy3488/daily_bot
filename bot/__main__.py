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


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    engine = make_engine(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.update.outer_middleware(WhitelistMiddleware(settings.owner_id))
    dp.update.outer_middleware(DbSessionMiddleware(make_sessionmaker(engine), settings.tz))
    dp.include_router(build_router())

    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

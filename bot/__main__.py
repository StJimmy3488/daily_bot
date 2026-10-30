import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.assistant import Assistant
from bot.config import get_settings
from bot.db.session import make_engine, make_sessionmaker
from bot.handlers import build_router
from bot.handlers.common import COMMANDS
from bot.middlewares import DbSessionMiddleware, WhitelistMiddleware
from bot.scheduler import PlannerScheduler
from bot.transcribe import Transcriber


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    engine = make_engine(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sessionmaker = make_sessionmaker(engine)
    # In a private chat the chat id equals the user id.
    scheduler = PlannerScheduler(bot, sessionmaker, chat_id=settings.owner_id, tz=settings.tz)
    assistant = Assistant(settings.anthropic_api_key, settings.ai_model) if settings.anthropic_api_key else None
    if assistant is None:
        logging.warning("ANTHROPIC_API_KEY not set: using the regex parser only")
    transcriber = Transcriber(settings.whisper_model)
    dp = Dispatcher(scheduler=scheduler, assistant=assistant, transcriber=transcriber)

    dp.update.outer_middleware(WhitelistMiddleware(settings.owner_id))
    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker, settings.tz))
    dp.include_router(build_router())

    await bot.set_my_commands(COMMANDS)
    await scheduler.start()
    warm_up = asyncio.create_task(transcriber.warm_up())  # keep a reference so it isn't GC'd
    try:
        await dp.start_polling(bot)
    finally:
        warm_up.cancel()
        scheduler.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

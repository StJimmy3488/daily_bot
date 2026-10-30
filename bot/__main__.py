import asyncio
import logging

import uvicorn

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.assistant import Assistant
from bot.config import get_settings
from bot.db.session import make_engine, make_sessionmaker
from bot.handlers import build_router
from bot.google_calendar import GoogleCalendar
from bot.handlers.common import COMMANDS
from bot.middlewares import DbSessionMiddleware, WhitelistMiddleware
from bot.scheduler import PlannerScheduler
from bot.transcribe import Transcriber
from bot.web import WebServer, create_app


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()

    engine = make_engine(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sessionmaker = make_sessionmaker(engine)
    gcal = None
    if settings.google_client_id and settings.google_client_secret:
        gcal = GoogleCalendar(settings.google_client_id, settings.google_client_secret, settings.public_url)
    # In a private chat the chat id equals the user id.
    scheduler = PlannerScheduler(bot, sessionmaker, chat_id=settings.owner_id, tz=settings.tz, gcal=gcal)
    assistant = None
    if settings.anthropic_api_key:
        assistant = Assistant(settings.anthropic_api_key, settings.ai_model, settings.ai_plan_model)
    if assistant is None:
        logging.warning("ANTHROPIC_API_KEY not set: using the regex parser only")
    transcriber = Transcriber(settings.whisper_model)
    dp = Dispatcher(scheduler=scheduler, assistant=assistant, transcriber=transcriber, gcal=gcal)

    app = create_app(bot, sessionmaker, settings.owner_id, gcal, on_connected=scheduler.calendar_sync)
    web = WebServer(uvicorn.Config(app, host="0.0.0.0", port=settings.web_port, lifespan="off", log_level="warning"))

    dp.update.outer_middleware(WhitelistMiddleware(settings.owner_id))
    dp.update.outer_middleware(DbSessionMiddleware(sessionmaker, settings.tz))
    dp.include_router(build_router())

    await bot.set_my_commands(COMMANDS)
    await scheduler.start()
    # Keep references so the tasks aren't garbage-collected.
    warm_up = asyncio.create_task(transcriber.warm_up())
    web_task = asyncio.create_task(web.serve())
    try:
        await dp.start_polling(bot)
    finally:
        web.should_exit = True
        await web_task
        warm_up.cancel()
        scheduler.shutdown()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

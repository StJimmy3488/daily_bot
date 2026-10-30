import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import planning
from bot.clock import local_today
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore

log = logging.getLogger(__name__)

ROLLOVER_AT = time(0, 1)
REMINDER_TICK_SECONDS = 30


class PlannerScheduler:
    """In-memory APScheduler. Durable state lives in the DB (reminders, day_plans),
    so jobs are simply rebuilt on startup and missed daily jobs are caught up."""

    def __init__(self, bot: Bot, sessionmaker: async_sessionmaker, chat_id: int, tz: ZoneInfo):
        self.bot = bot
        self.sessionmaker = sessionmaker
        self.chat_id = chat_id
        self.tz = tz
        self.scheduler = AsyncIOScheduler(timezone=tz)

    async def _run(self, job: Callable[[TaskRepo, SettingsStore], Awaitable[None]]) -> None:
        try:
            async with self.sessionmaker() as session, session.begin():
                await job(TaskRepo(session, self.tz), SettingsStore(session))
        except Exception:
            log.exception("Scheduled job failed")

    async def morning(self) -> None:
        await self._run(lambda repo, _: planning.send_brief(self.bot, self.chat_id, repo, local_today(self.tz)))

    async def evening(self) -> None:
        await self._run(lambda repo, _: planning.send_review(self.bot, self.chat_id, repo, local_today(self.tz)))

    async def reminders(self) -> None:
        await self._run(
            lambda repo, store: planning.send_due_reminders(self.bot, self.chat_id, repo, store, local_today(self.tz))
        )

    async def rollover(self) -> None:
        async def job(repo: TaskRepo, _: SettingsStore) -> None:
            if moved := await repo.rollover(local_today(self.tz)):
                log.info("Rolled over %d task(s)", moved)

        await self._run(job)

    def _cron(self, t: time) -> CronTrigger:
        return CronTrigger(hour=t.hour, minute=t.minute, timezone=self.tz)

    def set_daily_time(self, job_id: str, t: time) -> None:
        self.scheduler.reschedule_job(job_id, trigger=self._cron(t))

    async def start(self) -> None:
        async with self.sessionmaker() as session:
            store = SettingsStore(session)
            morning, evening = await store.get_time("morning"), await store.get_time("evening")

        s = self.scheduler
        s.add_job(self.morning, self._cron(morning), id="morning")
        s.add_job(self.evening, self._cron(evening), id="evening")
        s.add_job(self.rollover, self._cron(ROLLOVER_AT), id="rollover")
        s.add_job(self.reminders, IntervalTrigger(seconds=REMINDER_TICK_SECONDS), id="reminders", max_instances=1)
        s.start()
        await self._catch_up(morning, evening)

    async def _catch_up(self, morning: time, evening: time) -> None:
        """Run whatever daily job was missed while the bot was down."""
        await self.rollover()
        now = datetime.now(self.tz).time()
        async with self.sessionmaker() as session:
            plan = await TaskRepo(session, self.tz).get_plan(local_today(self.tz))
            brief_sent, reviewed = plan is not None, plan is not None and plan.reviewed_at is not None
        if morning <= now < evening and not brief_sent:
            log.info("Catching up on the morning brief")
            await self.morning()
        elif now >= evening and not reviewed:
            log.info("Catching up on the evening review")
            await self.evening()

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.clock import day_bounds_utc, local_to_utc, local_today, utcnow
from bot.db.models import AiCall, AiProposal, CalendarEvent, DayPlan, Event, Reminder, Task, TaskStatus
from bot.recurrence import next_occurrence


class TaskRepo:
    def __init__(self, session: AsyncSession, tz: ZoneInfo):
        self.session = session
        self.tz = tz

    async def _log(self, task: Task, action: str, payload: dict | None = None) -> None:
        self.session.add(Event(task_id=task.id, action=action, payload=payload))

    async def _clear_pending_reminders(self, task: Task) -> None:
        await self.session.execute(
            delete(Reminder).where(Reminder.task_id == task.id, Reminder.sent_at.is_(None))
        )

    async def _sync_reminder(self, task: Task) -> None:
        """Keep exactly one pending reminder per open task with a date and time."""
        await self._clear_pending_reminders(task)
        if task.status != TaskStatus.TODO or not (task.due_date and task.due_time):
            return
        fire_at = local_to_utc(task.due_date, task.due_time, self.tz)
        if fire_at > utcnow():
            self.session.add(Reminder(task_id=task.id, fire_at=fire_at))

    # --- tasks ---

    async def get(self, task_id: int) -> Task | None:
        return await self.session.get(Task, task_id)

    async def get_many(self, ids: list[int]) -> list[Task]:
        """Tasks in the order of `ids`, skipping missing ones."""
        if not ids:
            return []
        by_id = {t.id: t for t in await self.session.scalars(select(Task).where(Task.id.in_(ids)))}
        return [by_id[i] for i in ids if i in by_id]

    async def create(
        self,
        title: str,
        priority: int | None = None,
        due_date: date | None = None,
        due_time: time | None = None,
        recurrence_rule: str | None = None,
        est_minutes: int | None = None,
    ) -> Task:
        task = Task(
            title=title,
            priority=priority or 2,
            due_date=due_date,
            due_time=due_time,
            recurrence_rule=recurrence_rule,
            est_minutes=est_minutes,
        )
        self.session.add(task)
        await self.session.flush()
        await self._log(task, "created")
        await self._sync_reminder(task)
        return task

    async def list_today(self, today: date) -> list[Task]:
        """Due today plus everything overdue."""
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.TODO, Task.due_date <= today)
            .order_by(Task.due_date, Task.priority, Task.due_time.is_(None), Task.due_time, Task.id)
        )
        return list(await self.session.scalars(stmt))

    async def list_inbox(self) -> list[Task]:
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.TODO, Task.due_date.is_(None))
            .order_by(Task.priority, Task.created_at)
        )
        return list(await self.session.scalars(stmt))

    async def list_open(self) -> list[Task]:
        """All open tasks, dated first, for the LLM prompt."""
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.TODO)
            .order_by(Task.due_date.is_(None), Task.due_date, Task.due_time, Task.id)
        )
        return list(await self.session.scalars(stmt))

    async def done_on(self, day: date) -> list[Task]:
        start, end = day_bounds_utc(day, self.tz)
        stmt = select(Task).where(Task.status == TaskStatus.DONE, Task.done_at >= start, Task.done_at < end)
        return list(await self.session.scalars(stmt))

    async def _spawn_next(self, task: Task) -> Task | None:
        if not (task.recurrence_rule and task.due_date):
            return None
        nxt = next_occurrence(task.recurrence_rule, task.due_date, local_today(self.tz))
        if nxt is None:
            return None
        return await self.create(
            task.title, task.priority, nxt, task.due_time, task.recurrence_rule, task.est_minutes
        )

    async def complete(self, task: Task) -> Task | None:
        """Close the task; for a recurring one, return the freshly spawned next occurrence."""
        task.status = TaskStatus.DONE
        task.done_at = utcnow()
        await self._log(task, "done")
        await self._sync_reminder(task)
        return await self._spawn_next(task)

    async def drop(self, task: Task) -> Task | None:
        """Dropping one occurrence of a recurring task keeps the series going."""
        task.status = TaskStatus.DROPPED
        await self._log(task, "dropped")
        await self._sync_reminder(task)
        return await self._spawn_next(task)

    async def reschedule(self, task: Task, new_date: date | None, new_time: time | None = None) -> None:
        old = task.due_date
        task.due_date = new_date
        if new_time is not None:
            task.due_time = new_time
        await self._log(
            task,
            "moved",
            {"from": old.isoformat() if old else None, "to": new_date.isoformat() if new_date else None},
        )
        await self._sync_reminder(task)

    async def update(
        self,
        task: Task,
        title: str | None = None,
        priority: int | None = None,
        recurrence_rule: str | None = None,
        stop_repeating: bool = False,
    ) -> None:
        changes = {}
        if stop_repeating and task.recurrence_rule:
            changes["recurrence_rule"] = task.recurrence_rule
            task.recurrence_rule = None
        elif recurrence_rule and recurrence_rule != task.recurrence_rule:
            changes["recurrence_rule"] = task.recurrence_rule
            task.recurrence_rule = recurrence_rule
        if title and title != task.title:
            changes["title"] = task.title
            task.title = title
        if priority and priority != task.priority:
            changes["priority"] = task.priority
            task.priority = priority
        if changes:
            await self._log(task, "edited", {"old": changes})

    async def rollover(self, today: date) -> int:
        """Move every open task from past days to today; each move counts as a slip."""
        stmt = select(Task).where(Task.status == TaskStatus.TODO, Task.due_date < today)
        tasks = list(await self.session.scalars(stmt))
        for task in tasks:
            await self._log(task, "slipped", {"from": task.due_date.isoformat()})
            task.due_date = today
            await self._sync_reminder(task)
        return len(tasks)

    # --- reminders ---

    async def snooze(self, task: Task, minutes: int) -> None:
        await self._clear_pending_reminders(task)
        self.session.add(Reminder(task_id=task.id, fire_at=utcnow() + timedelta(minutes=minutes)))
        await self._log(task, "snoozed", {"minutes": minutes})

    async def due_reminders(self) -> list[tuple[Reminder, Task]]:
        stmt = (
            select(Reminder, Task)
            .join(Task, Task.id == Reminder.task_id)
            .where(Reminder.sent_at.is_(None), Reminder.fire_at <= utcnow(), Task.status == TaskStatus.TODO)
            .order_by(Reminder.fire_at)
        )
        return [(r, t) for r, t in await self.session.execute(stmt)]

    # --- day plans ---

    async def get_plan(self, day: date) -> DayPlan | None:
        return await self.session.get(DayPlan, day)

    async def save_plan(self, day: date, task_ids: list[int]) -> DayPlan:
        plan = await self.get_plan(day)
        if plan is None:
            plan = DayPlan(date=day, task_ids=task_ids)
            self.session.add(plan)
        else:
            plan.task_ids = list(task_ids)  # new list so the JSON change is detected
        return plan

    # --- AI ---

    async def log_ai_call(self, model: str, purpose: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self.session.add(
            AiCall(model=model, purpose=purpose, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost_usd)
        )

    async def ai_usage_since(self, since: datetime) -> tuple[int, float]:
        stmt = select(func.count(AiCall.id), func.coalesce(func.sum(AiCall.cost_usd), 0.0)).where(AiCall.at >= since)
        count, cost = (await self.session.execute(stmt)).one()
        return count, float(cost)

    async def create_proposal(self, actions: list[dict]) -> AiProposal:
        proposal = AiProposal(actions=actions, selected=list(range(len(actions))))
        self.session.add(proposal)
        await self.session.flush()
        return proposal

    async def get_proposal(self, proposal_id: int) -> AiProposal | None:
        return await self.session.get(AiProposal, proposal_id)

    # --- calendar ---

    async def events_between(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        stmt = (
            select(CalendarEvent)
            .where(CalendarEvent.start_at < end, CalendarEvent.end_at > start)
            .order_by(CalendarEvent.all_day.desc(), CalendarEvent.start_at)
        )
        return list(await self.session.scalars(stmt))

    async def events_on(self, day: date) -> list[CalendarEvent]:
        return await self.events_between(*day_bounds_utc(day, self.tz))

    async def events_starting_soon(self, within: timedelta) -> list[CalendarEvent]:
        now = utcnow()
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.all_day.is_(False),
                CalendarEvent.notified_at.is_(None),
                CalendarEvent.start_at > now,
                CalendarEvent.start_at <= now + within,
            )
            .order_by(CalendarEvent.start_at)
        )
        return list(await self.session.scalars(stmt))

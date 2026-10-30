from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.clock import utcnow
from bot.db.models import Event, Task, TaskStatus


class TaskRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _log(self, task: Task, action: str, payload: dict | None = None) -> None:
        self.session.add(Event(task_id=task.id, action=action, payload=payload))

    async def get(self, task_id: int) -> Task | None:
        return await self.session.get(Task, task_id)

    async def create(
        self,
        title: str,
        priority: int | None = None,
        due_date: date | None = None,
        due_time: time | None = None,
    ) -> Task:
        task = Task(title=title, priority=priority or 2, due_date=due_date, due_time=due_time)
        self.session.add(task)
        await self.session.flush()
        await self._log(task, "created")
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

    async def complete(self, task: Task) -> None:
        task.status = TaskStatus.DONE
        task.done_at = utcnow()
        await self._log(task, "done")

    async def drop(self, task: Task) -> None:
        task.status = TaskStatus.DROPPED
        await self._log(task, "dropped")

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

    async def update(self, task: Task, title: str | None = None, priority: int | None = None) -> None:
        changes = {}
        if title and title != task.title:
            changes["title"] = task.title
            task.title = title
        if priority and priority != task.priority:
            changes["priority"] = task.priority
            task.priority = priority
        if changes:
            await self._log(task, "edited", {"old": changes})

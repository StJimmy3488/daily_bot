"""Describe and apply the task actions proposed by the assistant."""

from datetime import date
from html import escape

from bot.assistant import Action, CompleteAction, CreateAction, DropAction, UpdateAction
from bot.db.models import Task, TaskStatus
from bot.formatting import PRIORITY_MARK, format_date
from bot.repo import TaskRepo


def _when(d: date | None, t, today: date) -> str:
    parts = [format_date(d, today) if d else "inbox"]
    if t:
        parts.append(f"{t:%H:%M}")
    return " ".join(parts)


def describe(action: Action, tasks: dict[int, Task], today: date) -> str:
    """One plain-text line (used in buttons and summaries)."""
    if isinstance(action, CreateAction):
        return f"➕ {PRIORITY_MARK[action.priority]}{action.title} · {_when(action.due_date, action.due_time, today)}"

    task = tasks.get(action.id)
    name = task.title if task else f"#{action.id} (missing)"
    if isinstance(action, CompleteAction):
        return f"✅ {name}"
    if isinstance(action, DropAction):
        return f"🗑 {name}"

    changes = []
    if action.title:
        changes.append(f"“{action.title}”")
    if action.unschedule:
        changes.append("→ inbox")
    elif action.due_date or action.due_time:
        changes.append("→ " + _when(action.due_date or (task.due_date if task else None), action.due_time, today))
    if action.priority:
        changes.append(f"priority {action.priority}")
    return f"✏️ {name}: {', '.join(changes) or 'no change'}"


def preview_text(actions: list[Action], tasks: dict[int, Task], today: date, reply: str) -> str:
    lines = []
    if reply:
        lines += [escape(reply), ""]
    lines.append("<b>Here's what I understood</b> — tap to include or skip, then save:")
    lines += [escape(describe(a, tasks, today)) for a in actions]
    return "\n".join(lines)


async def apply(repo: TaskRepo, action: Action, today: date) -> Task | None:
    """Apply one action. Returns the affected task, or None if it no longer exists/is closed."""
    if isinstance(action, CreateAction):
        due_date = action.due_date or (today if action.due_time else None)
        return await repo.create(action.title, action.priority, due_date, action.due_time)

    task = await repo.get(action.id)
    if task is None or task.status != TaskStatus.TODO:
        return None
    if isinstance(action, CompleteAction):
        await repo.complete(task)
    elif isinstance(action, DropAction):
        await repo.drop(task)
    elif isinstance(action, UpdateAction):
        await repo.update(task, title=action.title, priority=action.priority)
        if action.unschedule:
            await repo.reschedule(task, None)
        elif action.due_date or action.due_time:
            # A bare time keeps the task's day (or pulls an inbox task into today).
            await repo.reschedule(task, action.due_date or task.due_date or today, action.due_time)
    return task

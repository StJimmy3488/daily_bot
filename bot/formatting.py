from datetime import date
from html import escape

from bot.db.models import Task

PRIORITY_MARK = {1: "🔴 ", 2: "", 3: "🔵 "}


def format_date(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta < 0:
        return f"⚠️ overdue since {d:%a %d.%m}"
    return f"{d:%a %d.%m}"


def format_task(task: Task, today: date) -> str:
    line = f"{PRIORITY_MARK.get(task.priority, '')}<b>{escape(task.title)}</b>"
    meta = []
    if task.due_date:
        meta.append(f"📅 {format_date(task.due_date, today)}")
    else:
        meta.append("📥 inbox")
    if task.due_time:
        meta.append(f"⏰ {task.due_time:%H:%M}")
    return f"{line}\n<i>{' · '.join(meta)}</i>"


def format_closed(task: Task, icon: str) -> str:
    return f"{icon} <s>{escape(task.title)}</s>"

from datetime import date
from html import escape
from zoneinfo import ZoneInfo

from bot.clock import as_utc
from bot.db.models import CalendarEvent, Task
from bot.recurrence import describe_rule

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
    if task.recurrence_rule:
        meta.append(f"🔁 {describe_rule(task.recurrence_rule)}")
    return f"{line}\n<i>{' · '.join(meta)}</i>"


def format_closed(task: Task, icon: str) -> str:
    return f"{icon} <s>{escape(task.title)}</s>"


def format_line(task: Task, today: date) -> str:
    """One-line variant for lists inside a single message."""
    meta = []
    if task.due_time:
        meta.append(f"⏰ {task.due_time:%H:%M}")
    if task.due_date is None:
        meta.append("📥 inbox")
    elif task.due_date < today:
        meta.append("⚠️ overdue")
    suffix = f" <i>· {' · '.join(meta)}</i>" if meta else ""
    return f"{PRIORITY_MARK.get(task.priority, '')}{escape(task.title)}{suffix}"


def format_event(event: CalendarEvent, tz: ZoneInfo, with_link: bool = False) -> str:
    title = escape(event.title)
    if with_link and event.link:
        title = f'<a href="{escape(event.link, quote=True)}">{title}</a>'
    if event.all_day:
        return f"📅 all day · {title}"
    start, end = as_utc(event.start_at).astimezone(tz), as_utc(event.end_at).astimezone(tz)
    return f"📅 {start:%H:%M}–{end:%H:%M} · {title}"

"""Describe and apply the actions proposed by the assistant."""

from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from bot.assistant import (
    Action,
    CompleteAction,
    CreateAction,
    DropAction,
    EventAction,
    EventDeleteAction,
    EventUpdateAction,
    PlanDayAction,
    UpdateAction,
)
from bot.calendar_edit import EventChange, delete_event, update_event
from bot.clock import as_utc
from bot.db.models import CalendarEvent, Task, TaskStatus
from bot.formatting import PRIORITY_MARK, format_date
from bot.google_calendar import GoogleCalendar
from bot.recurrence import describe_rule, first_occurrence
from bot.repo import TaskRepo


def _when(d: date | None, t, today: date) -> str:
    parts = [format_date(d, today) if d else "inbox"]
    if t:
        parts.append(f"{t:%H:%M}")
    return " ".join(parts)


def describe(
    action: Action, tasks: dict[int, Task], today: date, events: dict[int, CalendarEvent] | None = None
) -> str:
    """One plain-text line (used in buttons and summaries)."""
    if isinstance(action, EventDeleteAction | EventUpdateAction):
        event = (events or {}).get(action.event_id)
        name = event.title if event else f"event #{action.event_id} (missing)"
        if isinstance(action, EventDeleteAction):
            return f"📅🗑 Cancel “{name}”"
        changes = []
        if action.title:
            changes.append(f"“{action.title}”")
        if action.day or action.start:
            when = format_date(action.day, today) if action.day else ""
            changes.append(f"→ {when} {action.start:%H:%M}".replace("  ", " ") if action.start else f"→ {when}")
        if action.minutes:
            changes.append(f"{action.minutes} min")
        return f"📅✏️ {name}: {', '.join(changes) or 'no change'}"
    if isinstance(action, CreateAction):
        line = f"➕ {PRIORITY_MARK[action.priority]}{action.title} · {_when(action.due_date, action.due_time, today)}"
        return line + (f" · 🔁 {describe_rule(action.recurrence)}" if action.recurrence else "")
    if isinstance(action, EventAction):
        end = (datetime.combine(action.day, action.start) + timedelta(minutes=action.minutes)).time()
        return f"📅 {action.title} · {format_date(action.day, today)} {action.start:%H:%M}–{end:%H:%M}"
    if isinstance(action, PlanDayAction):
        return "🧠 Plan the day"

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
    if action.stop_repeating:
        changes.append("stop repeating")
    elif action.recurrence:
        changes.append(f"🔁 {describe_rule(action.recurrence)}")
    return f"✏️ {name}: {', '.join(changes) or 'no change'}"


def preview_text(
    actions: list[Action],
    tasks: dict[int, Task],
    today: date,
    reply: str,
    events: dict[int, CalendarEvent] | None = None,
) -> str:
    lines = []
    if reply:
        lines += [escape(reply), ""]
    lines.append("<b>Here's what I understood</b> — tap to include or skip, then save:")
    lines += [escape(describe(a, tasks, today, events)) for a in actions]
    if any((events or {}).get(getattr(a, "event_id", None)) and events[a.event_id].has_guests for a in actions):
        lines.append("<i>Guests will get Google's update email.</i>")
    return "\n".join(lines)


async def apply(repo: TaskRepo, action: Action, today: date) -> Task | None:
    """Apply one task action. Returns the affected task, or None if it no longer exists/is closed."""
    if isinstance(action, CreateAction):
        due_date = action.due_date or (today if action.due_time else None)
        if action.recurrence and due_date is None:
            due_date = first_occurrence(action.recurrence, today)
        return await repo.create(action.title, action.priority, due_date, action.due_time, action.recurrence)

    task = await repo.get(action.id)
    if task is None or task.status != TaskStatus.TODO:
        return None
    if isinstance(action, CompleteAction):
        await repo.complete(task)
    elif isinstance(action, DropAction):
        await repo.drop(task)
    elif isinstance(action, UpdateAction):
        await repo.update(
            task,
            title=action.title,
            priority=action.priority,
            recurrence_rule=action.recurrence,
            stop_repeating=action.stop_repeating,
        )
        if action.unschedule:
            await repo.reschedule(task, None)
        elif action.due_date or action.due_time:
            # A bare time keeps the task's day (or pulls an inbox task into today).
            await repo.reschedule(task, action.due_date or task.due_date or today, action.due_time)
        elif action.recurrence and task.due_date is None:
            await repo.reschedule(task, first_occurrence(action.recurrence, today))
    return task


async def create_event(gcal: GoogleCalendar, refresh_token: str, action: EventAction, tz: ZoneInfo) -> str | None:
    """Write a confirmed event to the primary calendar. Returns its link."""
    start = datetime.combine(action.day, action.start, tzinfo=tz)
    created = await gcal.insert_event(
        refresh_token, action.title, start, start + timedelta(minutes=action.minutes), str(tz)
    )
    return created.get("htmlLink")


def event_change(action: EventUpdateAction, event: CalendarEvent, tz: ZoneInfo) -> EventChange:
    """Turn "move to Friday 15:00 for 30 min" into new start/end (or a new day for all-day events)."""
    if event.all_day:
        return EventChange(title=action.title, day=action.day)
    current = as_utc(event.start_at).astimezone(tz)
    start = None
    if action.day or action.start:
        start = datetime.combine(action.day or current.date(), action.start or current.time(), tzinfo=tz)
    end = None
    if action.minutes:
        end = (start or current) + timedelta(minutes=action.minutes)
    return EventChange(title=action.title, start=start, end=end)


async def apply_event_edit(
    session: AsyncSession,
    gcal: GoogleCalendar,
    token: str,
    action: EventUpdateAction | EventDeleteAction,
    event: CalendarEvent,
    tz: ZoneInfo,
) -> None:
    """Raises calendar_edit.EventEditError with a user-facing reason."""
    if isinstance(action, EventDeleteAction):
        await delete_event(session, gcal, token, event)
    else:
        await update_event(session, gcal, token, event, event_change(action, event, tz), tz)

from datetime import date, timedelta

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Task

WEEKDAY_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


class TaskCb(CallbackData, prefix="t"):
    action: str  # done | drop | today | tomorrow | pick | back | snooze
    id: int
    minutes: int = 0  # for snooze


class PlanCb(CallbackData, prefix="pl"):
    action: str  # accept | edit | toggle
    day: int  # date.toordinal(), so a stale brief can't touch another day
    id: int = 0  # task id for toggle


class PickCb(CallbackData, prefix="p"):
    id: int
    day: int  # date.toordinal()


class AddCb(CallbackData, prefix="a"):
    field: str  # date | prio
    value: str


def task_kb(task: Task) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if task.due_date is None:
        b.button(text="📌 Today", callback_data=TaskCb(action="today", id=task.id))
        b.button(text="➡️ Tomorrow", callback_data=TaskCb(action="tomorrow", id=task.id))
        b.button(text="📅 Pick", callback_data=TaskCb(action="pick", id=task.id))
        b.button(text="🗑 Drop", callback_data=TaskCb(action="drop", id=task.id))
        b.adjust(3, 1)
    else:
        b.button(text="✅ Done", callback_data=TaskCb(action="done", id=task.id))
        b.button(text="➡️ Tomorrow", callback_data=TaskCb(action="tomorrow", id=task.id))
        b.button(text="📅", callback_data=TaskCb(action="pick", id=task.id))
        b.button(text="🗑", callback_data=TaskCb(action="drop", id=task.id))
        b.adjust(4)
    return b.as_markup()


def ping_kb(task: Task) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Done", callback_data=TaskCb(action="done", id=task.id))
    b.button(text="+30 min", callback_data=TaskCb(action="snooze", id=task.id, minutes=30))
    b.button(text="+2 h", callback_data=TaskCb(action="snooze", id=task.id, minutes=120))
    b.button(text="➡️ Tomorrow", callback_data=TaskCb(action="tomorrow", id=task.id))
    b.adjust(4)
    return b.as_markup()


def review_kb(task: Task) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Done", callback_data=TaskCb(action="done", id=task.id))
    b.button(text="➡️ Tomorrow", callback_data=TaskCb(action="tomorrow", id=task.id))
    b.button(text="🗑 Drop", callback_data=TaskCb(action="drop", id=task.id))
    return b.as_markup()


def brief_kb(day: date) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Accept plan", callback_data=PlanCb(action="accept", day=day.toordinal()))
    b.button(text="✏️ Edit", callback_data=PlanCb(action="edit", day=day.toordinal()))
    return b.as_markup()


def plan_edit_kb(day: date, proposed: list[Task], selected: set[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for task in proposed:
        mark = "☑️" if task.id in selected else "⬜️"
        title = task.title if len(task.title) <= 32 else task.title[:31] + "…"
        b.button(text=f"{mark} {title}", callback_data=PlanCb(action="toggle", day=day.toordinal(), id=task.id))
    b.button(text=f"✅ Accept ({len(selected)})", callback_data=PlanCb(action="accept", day=day.toordinal()))
    b.adjust(1)
    return b.as_markup()


def plan_ids_from_markup(markup: InlineKeyboardMarkup | None) -> list[int]:
    """The proposed task ids, recovered from the toggle buttons of an edit keyboard."""
    if markup is None:
        return []
    ids = []
    for row in markup.inline_keyboard:
        for button in row:
            if (button.callback_data or "").startswith(PlanCb.__prefix__ + ":"):
                cb = PlanCb.unpack(button.callback_data)
                if cb.action == "toggle":
                    ids.append(cb.id)
    return ids


def pick_date_kb(task_id: int, today: date) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i in range(14):
        d = today + timedelta(days=i)
        b.button(
            text=f"{WEEKDAY_SHORT[d.weekday()]} {d.day}",
            callback_data=PickCb(id=task_id, day=d.toordinal()),
        )
    b.button(text="📥 Inbox", callback_data=PickCb(id=task_id, day=0))
    b.button(text="« Back", callback_data=TaskCb(action="back", id=task_id))
    b.adjust(7, 7, 2)
    return b.as_markup()


def add_date_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value, text in [("inbox", "📥 Inbox"), ("today", "📌 Today"), ("tomorrow", "➡️ Tomorrow")]:
        b.button(text=text, callback_data=AddCb(field="date", value=value))
    return b.as_markup()


def add_prio_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value, text in [("1", "🔴 High"), ("2", "⚪️ Normal"), ("3", "🔵 Low")]:
        b.button(text=text, callback_data=AddCb(field="prio", value=value))
    return b.as_markup()


def task_id_from_message(message: Message) -> int | None:
    """Recover the task a bot message is about from its inline buttons."""
    markup = message.reply_markup
    if not isinstance(markup, InlineKeyboardMarkup):
        return None
    for row in markup.inline_keyboard:
        for button in row:
            button: InlineKeyboardButton
            data = button.callback_data or ""
            for cb in (TaskCb, PickCb):
                if data.startswith(cb.__prefix__ + ":"):
                    return cb.unpack(data).id
    return None

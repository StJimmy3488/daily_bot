"""Morning brief, evening review and reminder delivery.

Shared by the scheduled jobs and the /plan and /review commands.
"""

import logging
from datetime import date, time, timedelta

from aiogram import Bot

from bot.clock import utcnow
from bot.db.models import DayPlan, Task, TaskStatus
from bot.formatting import format_line, format_task
from bot.keyboards import brief_kb, ping_kb, review_kb
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore

log = logging.getLogger(__name__)

INBOX_IN_BRIEF = 3


def _plan_order(task: Task) -> tuple:
    return task.priority, task.due_time is None, task.due_time or time(), task.id


def brief_text(today: date, tasks: list[Task]) -> str:
    lines = [f"☀️ <b>Good morning — {today:%a %d.%m}</b>", ""]
    lines += [f"{i}. {format_line(t, today)}" for i, t in enumerate(tasks, 1)]
    lines += ["", "Accept the plan or edit it."]
    return "\n".join(lines)


def plan_text(today: date, tasks: list[Task]) -> str:
    lines = [f"📋 <b>Plan for {today:%a %d.%m}</b> — {len(tasks)} task(s)", ""]
    lines += [f"{i}. {format_line(t, today)}" for i, t in enumerate(tasks, 1)]
    lines += ["", "/today for buttons"]
    return "\n".join(lines)


async def send_brief(bot: Bot, chat_id: int, repo: TaskRepo, today: date) -> None:
    dated = await repo.list_today(today)
    inbox = (await repo.list_inbox())[:INBOX_IN_BRIEF]
    proposed = sorted(dated + inbox, key=_plan_order)
    # The draft plan doubles as the "brief already sent today" marker.
    plan = await repo.save_plan(today, [t.id for t in proposed])
    plan.accepted_at = None

    if not proposed:
        await bot.send_message(chat_id, f"☀️ <b>Good morning — {today:%a %d.%m}</b>\n\nNothing planned and the inbox is empty.")
        return
    await bot.send_message(chat_id, brief_text(today, proposed), reply_markup=brief_kb(today))


async def accept_plan(repo: TaskRepo, plan: DayPlan, proposed_ids: list[int], today: date) -> list[Task]:
    """Pull chosen tasks into today; push dated tasks that were unticked to tomorrow."""
    chosen = await repo.get_many(plan.task_ids)
    for task in chosen:
        if task.status == TaskStatus.TODO and task.due_date != today:
            await repo.reschedule(task, today)
    for task in await repo.get_many([i for i in proposed_ids if i not in plan.task_ids]):
        if task.status == TaskStatus.TODO and task.due_date is not None and task.due_date <= today:
            await repo.reschedule(task, today + timedelta(days=1))
    plan.accepted_at = utcnow()
    return chosen


async def send_review(bot: Bot, chat_id: int, repo: TaskRepo, today: date) -> None:
    plan = await repo.get_plan(today)
    if plan is None or plan.accepted_at is None:
        # No accepted plan: review what actually happened today instead.
        ids = [t.id for t in await repo.done_on(today)] + [t.id for t in await repo.list_today(today)]
        plan = await repo.save_plan(today, ids)
    plan.reviewed_at = utcnow()

    tasks = await repo.get_many(plan.task_ids)
    if not tasks:
        await bot.send_message(chat_id, "🌙 Nothing was planned today. Rest well.")
        return
    done = sum(t.status == TaskStatus.DONE for t in tasks)
    still_open = [t for t in tasks if t.status == TaskStatus.TODO and t.due_date and t.due_date <= today]
    if not still_open:
        await bot.send_message(chat_id, f"🌙 Day closed — {done}/{len(tasks)} done 🎉")
        return

    await bot.send_message(chat_id, f"🌙 <b>Evening review</b> — {done}/{len(tasks)} done. What about these?")
    for task in still_open:
        await bot.send_message(chat_id, format_task(task, today), reply_markup=review_kb(task))


async def day_summary_if_closed(repo: TaskRepo, task: Task, today: date) -> str | None:
    """After a review button: return the closing line once nothing planned is left open."""
    plan = await repo.get_plan(today)
    if plan is None or plan.reviewed_at is None or task.id not in plan.task_ids:
        return None
    tasks = await repo.get_many(plan.task_ids)
    if any(t.status == TaskStatus.TODO and t.due_date and t.due_date <= today for t in tasks):
        return None
    done = sum(t.status == TaskStatus.DONE for t in tasks)
    return f"🌙 Day closed — {done}/{len(tasks)} done"


async def send_due_reminders(bot: Bot, chat_id: int, repo: TaskRepo, store: SettingsStore, today: date) -> None:
    if await store.is_muted(utcnow(), repo.tz):
        return  # pending reminders stay pending and go out once the mute ends
    for reminder, task in await repo.due_reminders():
        try:
            await bot.send_message(chat_id, f"⏰ {format_task(task, today)}", reply_markup=ping_kb(task))
        except Exception:
            log.exception("Failed to send reminder %s", reminder.id)
            continue
        reminder.sent_at = utcnow()

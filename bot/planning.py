"""Morning brief, evening review and reminder delivery.

Shared by the scheduled jobs and the /plan and /review commands.
"""

import logging
from datetime import date, datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot

from bot import actions as task_actions
from bot.assistant import Assistant, AssistantUnavailable, UpdateAction, dump_actions
from bot.clock import as_utc, utcnow
from bot.db.models import CalendarEvent, DayPlan, Task, TaskStatus
from bot.formatting import PRIORITY_MARK, format_event, format_line, format_task
from bot.keyboards import brief_kb, ping_kb, proposal_kb, review_kb
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore
from bot.smart_plan import default_order, fit_day

log = logging.getLogger(__name__)

INBOX_IN_BRIEF = 3


def _plan_order(task: Task) -> tuple:
    return task.priority, task.due_time is None, task.due_time or time(), task.id


HEADS_UP = timedelta(minutes=10)


def brief_text(today: date, tasks: list[Task], events: list[CalendarEvent], tz: ZoneInfo) -> str:
    lines = [f"☀️ <b>Good morning — {today:%a %d.%m}</b>", ""]
    if events:
        lines += ["<b>Meetings</b>", *[format_event(e, tz) for e in events], "", "<b>Tasks</b>"]
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

    events = await repo.events_on(today)
    if not proposed:
        text = f"☀️ <b>Good morning — {today:%a %d.%m}</b>\n\n"
        text += (
            "\n".join(format_event(e, repo.tz) for e in events) if events else "Nothing planned and the inbox is empty."
        )
        await bot.send_message(chat_id, text)
        return
    await bot.send_message(chat_id, brief_text(today, proposed, events, repo.tz), reply_markup=brief_kb(today))


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


async def send_meeting_headsups(bot: Bot, chat_id: int, repo: TaskRepo, store: SettingsStore) -> None:
    now = utcnow()
    if await store.is_quiet(now, repo.tz):
        return
    for event in await repo.events_starting_soon(HEADS_UP):
        minutes = max(1, round((as_utc(event.start_at) - now).total_seconds() / 60))
        try:
            await bot.send_message(chat_id, f"⏰ In {minutes} min:\n{format_event(event, repo.tz, with_link=True)}")
        except Exception:
            log.exception("Failed to send heads-up for event %s", event.id)
            continue
        event.notified_at = now


async def send_smart_plan(
    bot: Bot, chat_id: int, repo: TaskRepo, store: SettingsStore, assistant: Assistant | None, today: date
) -> None:
    """Order today's tasks (Claude if available), fit them around meetings, offer to set the times."""
    now = datetime.now(repo.tz)
    tasks = await repo.list_today(today)
    events = await repo.events_on(today)
    work = await store.work_hours()
    if not tasks:
        await bot.send_message(chat_id, "Nothing to plan — no open tasks for today. Check /inbox.")
        return

    order, minutes, note = default_order(tasks), {}, ""
    if assistant is not None:
        try:
            result = await assistant.order_day(tasks, events, work, now)
            await repo.log_ai_call(result.model, "plan", result.input_tokens, result.output_tokens, result.cost_usd)
            by_id = {t.id: t for t in tasks}
            order, minutes, note = [by_id[i] for i in result.ids], result.minutes, result.note
        except AssistantUnavailable as e:
            log.warning("Smart plan without AI (%s)", e)
    for task in tasks:
        if task.est_minutes is None and task.id in minutes:
            task.est_minutes = minutes[task.id]  # remember the estimate for next time

    plan = fit_day(today, order, minutes, events, work, repo.tz, now)
    lines = [f"🧠 <b>Smart plan — {today:%a %d.%m}</b> <i>(work {work[0]:%H:%M}–{work[1]:%H:%M})</i>", ""]
    for block in plan.blocks:
        icon = "📅" if block.is_meeting else ("⏰" if block.task.due_time else "▫️")
        mark = "" if block.is_meeting else PRIORITY_MARK.get(block.task.priority, "")
        lines.append(f"{block.start:%H:%M}–{block.end:%H:%M} {icon} {mark}{escape(block.title)}")
    if not plan.blocks:
        lines.append("No free working time left today.")
    if plan.unplaced:
        lines += ["", "⏳ <b>Didn't fit:</b> " + ", ".join(escape(t.title) for t in plan.unplaced)]
    if note:
        lines += ["", f"<i>{escape(note)}</i>"]

    actions = [
        UpdateAction(id=b.task.id, due_date=today, due_time=b.start.time())
        for b in plan.blocks
        if b.task is not None and b.task.due_time is None
    ]
    if not actions:
        await bot.send_message(chat_id, "\n".join(lines))
        return
    lines += ["", "Save to get a reminder at the start of each slot:"]
    proposal = await repo.create_proposal(dump_actions(actions))
    by_id = {t.id: t for t in tasks}
    labels = [task_actions.describe(a, by_id, today) for a in actions]
    await bot.send_message(
        chat_id, "\n".join(lines), reply_markup=proposal_kb(proposal.id, labels, set(proposal.selected))
    )

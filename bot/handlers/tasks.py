from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.clock import utcnow
from bot.db.models import TaskStatus
from bot.formatting import format_closed, format_task
from bot.keyboards import PickCb, TaskCb, pick_date_kb, task_kb
from bot.planning import day_summary_if_closed
from bot.repo import TaskRepo

router = Router()


@router.message(Command("today"))
async def cmd_today(message: Message, repo: TaskRepo, today: date) -> None:
    tasks = await repo.list_today(today)
    if not tasks:
        await message.answer("Nothing planned for today 🎉\nCheck /inbox for something to pull in.")
        return
    overdue = sum(1 for t in tasks if t.due_date < today)
    header = f"<b>Today · {today:%a %d.%m}</b> — {len(tasks)} task(s)"
    if overdue:
        header += f", {overdue} overdue"
    await message.answer(header)
    for task in tasks:
        await message.answer(format_task(task, today), reply_markup=task_kb(task))


@router.message(Command("inbox"))
async def cmd_inbox(message: Message, repo: TaskRepo, today: date) -> None:
    tasks = await repo.list_inbox()
    if not tasks:
        await message.answer("Inbox zero 📭")
        return
    await message.answer(f"<b>Inbox</b> — {len(tasks)} task(s)")
    for task in tasks:
        await message.answer(format_task(task, today), reply_markup=task_kb(task))


@router.callback_query(TaskCb.filter())
async def on_task_action(query: CallbackQuery, callback_data: TaskCb, repo: TaskRepo, today: date) -> None:
    task = await repo.get(callback_data.id)
    if task is None or task.status != TaskStatus.TODO:
        await query.answer("Already handled")
        await query.message.edit_reply_markup(reply_markup=None)
        return

    match callback_data.action:
        case "done" | "drop":
            closing = repo.complete if callback_data.action == "done" else repo.drop
            nxt = await closing(task)
            icon = "✅" if callback_data.action == "done" else "🗑"
            await query.message.edit_text(format_closed(task, icon))
            await query.answer("Done 💪" if callback_data.action == "done" else "Dropped")
            if nxt is not None:
                await query.message.answer(f"🔁 Next time:\n{format_task(nxt, today)}", reply_markup=task_kb(nxt))
        case "today" | "tomorrow":
            offset = 0 if callback_data.action == "today" else 1
            await repo.reschedule(task, today + timedelta(days=offset))
            await query.message.edit_text(format_task(task, today), reply_markup=task_kb(task))
            await query.answer(f"Moved to {callback_data.action}")
        case "snooze":
            await repo.snooze(task, callback_data.minutes)
            until = utcnow() + timedelta(minutes=callback_data.minutes)
            await query.message.edit_text(
                f"{format_task(task, today)}\n💤 snoozed until {until.astimezone(repo.tz):%H:%M}",
                reply_markup=task_kb(task),
            )
            await query.answer("Snoozed")
        case "pick":
            await query.message.edit_reply_markup(reply_markup=pick_date_kb(task.id, today))
            await query.answer()
        case "back":
            await query.message.edit_reply_markup(reply_markup=task_kb(task))
            await query.answer()

    if callback_data.action in {"done", "drop", "tomorrow"} and (
        summary := await day_summary_if_closed(repo, task, today)
    ):
        await query.message.answer(summary)


@router.callback_query(PickCb.filter())
async def on_pick_date(query: CallbackQuery, callback_data: PickCb, repo: TaskRepo, today: date) -> None:
    task = await repo.get(callback_data.id)
    if task is None or task.status != TaskStatus.TODO:
        await query.answer("Already handled")
        await query.message.edit_reply_markup(reply_markup=None)
        return
    new_date = date.fromordinal(callback_data.day) if callback_data.day else None
    await repo.reschedule(task, new_date)
    await query.message.edit_text(format_task(task, today), reply_markup=task_kb(task))
    await query.answer("Moved")

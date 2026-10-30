from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.db.models import TaskStatus
from bot.formatting import format_closed, format_task
from bot.keyboards import PickCb, TaskCb, pick_date_kb, task_kb
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
        case "done":
            await repo.complete(task)
            await query.message.edit_text(format_closed(task, "✅"))
            await query.answer("Done 💪")
        case "drop":
            await repo.drop(task)
            await query.message.edit_text(format_closed(task, "🗑"))
            await query.answer("Dropped")
        case "today" | "tomorrow":
            offset = 0 if callback_data.action == "today" else 1
            await repo.reschedule(task, today + timedelta(days=offset))
            await query.message.edit_text(format_task(task, today), reply_markup=task_kb(task))
            await query.answer(f"Moved to {callback_data.action}")
        case "pick":
            await query.message.edit_reply_markup(reply_markup=pick_date_kb(task.id, today))
            await query.answer()
        case "back":
            await query.message.edit_reply_markup(reply_markup=task_kb(task))
            await query.answer()


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

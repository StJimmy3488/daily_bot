from datetime import date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from bot.db.models import TaskStatus
from bot.formatting import format_task
from bot.keyboards import task_id_from_message, task_kb
from bot.parsing import parse_task
from bot.repo import TaskRepo

router = Router()


@router.message(StateFilter(None), F.text, F.reply_to_message.from_user.is_bot)
async def edit_by_reply(message: Message, repo: TaskRepo, today: date) -> None:
    original = message.reply_to_message
    task_id = task_id_from_message(original)
    task = await repo.get(task_id) if task_id else None
    if task is None or task.status != TaskStatus.TODO:
        await message.reply("Reply to an open task message to edit it.")
        return

    parsed = parse_task(message.text, today)
    await repo.update(task, title=parsed.title or None, priority=parsed.priority)
    if parsed.due_date or parsed.due_time:
        # A bare time keeps the task's day (or pulls an inbox task into today).
        new_date = parsed.due_date or task.due_date or today
        await repo.reschedule(task, new_date, parsed.due_time)

    await original.edit_text(format_task(task, today), reply_markup=task_kb(task))
    await message.reply("✏️ Updated")


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def capture(message: Message, repo: TaskRepo, today: date) -> None:
    parsed = parse_task(message.text, today)
    if not parsed.title:
        await message.reply("That's only a date — what's the task?")
        return
    # A bare time means today.
    due_date = parsed.due_date or (today if parsed.due_time else None)
    task = await repo.create(parsed.title, parsed.priority, due_date, parsed.due_time)
    await message.answer(format_task(task, today), reply_markup=task_kb(task))


@router.message(StateFilter(None), F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Unknown command. See /help")

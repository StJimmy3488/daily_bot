from datetime import date, time, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.formatting import format_task
from bot.keyboards import AddCb, add_date_kb, add_prio_kb, task_kb
from bot.parsing import parse_task
from bot.repo import TaskRepo

router = Router()


class AddTask(StatesGroup):
    title = State()
    when = State()
    priority = State()


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddTask.title)
    await message.answer("What's the task? (/cancel to stop)")


@router.message(AddTask.title, F.text)
async def add_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text.strip())
    await state.set_state(AddTask.when)
    await message.answer(
        "When? Pick below or type a date/time, e.g. <code>fri 14:30</code> or <code>25.11</code>",
        reply_markup=add_date_kb(),
    )


@router.callback_query(AddTask.when, AddCb.filter(F.field == "date"))
async def add_when_button(query: CallbackQuery, callback_data: AddCb, state: FSMContext, today: date) -> None:
    offsets = {"today": 0, "tomorrow": 1}
    due = today + timedelta(days=offsets[callback_data.value]) if callback_data.value in offsets else None
    await state.update_data(due_date=due.isoformat() if due else None, due_time=None)
    await state.set_state(AddTask.priority)
    await query.message.edit_text("Priority?", reply_markup=add_prio_kb())
    await query.answer()


@router.message(AddTask.when, F.text)
async def add_when_text(message: Message, state: FSMContext, today: date) -> None:
    parsed = parse_task(message.text, today)
    if parsed.due_time and not parsed.due_date:
        parsed.due_date = today
    if parsed.due_date is None or parsed.title:
        await message.answer(
            "Didn't get that date. Try <code>tomorrow</code>, <code>fri</code>, <code>25.11 9:00</code>"
        )
        return
    await state.update_data(
        due_date=parsed.due_date.isoformat(),
        due_time=parsed.due_time.isoformat() if parsed.due_time else None,
    )
    await state.set_state(AddTask.priority)
    await message.answer("Priority?", reply_markup=add_prio_kb())


@router.callback_query(AddTask.priority, AddCb.filter(F.field == "prio"))
async def add_priority(
    query: CallbackQuery, callback_data: AddCb, state: FSMContext, repo: TaskRepo, today: date
) -> None:
    data = await state.get_data()
    await state.clear()
    task = await repo.create(
        title=data["title"],
        priority=int(callback_data.value),
        due_date=date.fromisoformat(data["due_date"]) if data.get("due_date") else None,
        due_time=time.fromisoformat(data["due_time"]) if data.get("due_time") else None,
    )
    await query.message.edit_text(format_task(task, today), reply_markup=task_kb(task))
    await query.answer("Saved")

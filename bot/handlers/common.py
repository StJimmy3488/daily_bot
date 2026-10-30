from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, Message

router = Router()

COMMANDS = [
    BotCommand(command="today", description="Today's tasks + overdue"),
    BotCommand(command="inbox", description="Undated tasks"),
    BotCommand(command="add", description="Add a task step by step"),
    BotCommand(command="cancel", description="Cancel the current flow"),
    BotCommand(command="help", description="How to use the bot"),
]

HELP = """<b>Personal planner</b>

Send any message to capture a task:
<code>buy milk</code> → inbox
<code>call bank tomorrow !1</code> → tomorrow, high priority
<code>dentist fri 14:30</code> → next Friday at 14:30
<code>pay rent 25.11</code> → on 25 Nov

Dates: today, tomorrow/tmr, mon…sun, 25.11, 25.11.2027
Priority: !1 high, !2 normal, !3 low
Time: 14:30

<b>Reply</b> to any task message to edit it — new title, date or priority.

/today — today + overdue
/inbox — undated tasks
/add — guided entry"""


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.")

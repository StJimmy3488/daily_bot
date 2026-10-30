from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, Message

router = Router()

COMMANDS = [
    BotCommand(command="today", description="Today's tasks + overdue"),
    BotCommand(command="inbox", description="Undated tasks"),
    BotCommand(command="add", description="Add a task step by step"),
    BotCommand(command="plan", description="Morning brief now"),
    BotCommand(command="review", description="Evening review now"),
    BotCommand(command="focus", description="Mute reminders, e.g. /focus 90"),
    BotCommand(command="settings", description="Brief/review times, quiet hours"),
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

Tasks with a time get a reminder ⏰ with Done / +30 min / +2 h / Tomorrow.
Every morning you get a plan to accept, every evening a review.
Unfinished tasks roll over to the next day at midnight.

/today — today + overdue
/inbox — undated tasks
/add — guided entry
/plan — morning brief now
/review — evening review now
/focus 90 — mute reminders for 90 min (/focus off)
/settings — times and quiet hours"""


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.")

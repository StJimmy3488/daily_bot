import re
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot import planning
from bot.clock import parse_hhmm, utcnow
from bot.keyboards import PlanCb, plan_edit_kb, plan_ids_from_markup
from bot.repo import TaskRepo
from bot.scheduler import PlannerScheduler
from bot.settings_store import SettingsStore

router = Router()

HHMM = r"([01]?\d|2[0-3]):[0-5]\d"
TIME_RE = re.compile(rf"^{HHMM}$")
RANGE_RE = re.compile(rf"^{HHMM}-{HHMM}$")


@router.message(Command("plan"))
async def cmd_plan(message: Message, repo: TaskRepo, today: date) -> None:
    await planning.send_brief(message.bot, message.chat.id, repo, today)


@router.message(Command("review"))
async def cmd_review(message: Message, repo: TaskRepo, today: date) -> None:
    await planning.send_review(message.bot, message.chat.id, repo, today)


@router.callback_query(PlanCb.filter())
async def on_plan(query: CallbackQuery, callback_data: PlanCb, repo: TaskRepo, today: date) -> None:
    plan = await repo.get_plan(today)
    if callback_data.day != today.toordinal() or plan is None:
        await query.answer("This plan is from another day")
        await query.message.edit_reply_markup(reply_markup=None)
        return

    # Before "Edit" the proposal is the plan itself; afterwards it lives in the toggle buttons.
    proposed_ids = plan_ids_from_markup(query.message.reply_markup) or list(plan.task_ids)

    match callback_data.action:
        case "edit":
            proposed = await repo.get_many(proposed_ids)
            await query.message.edit_reply_markup(reply_markup=plan_edit_kb(today, proposed, set(plan.task_ids)))
            await query.answer("Tap to include or skip")
        case "toggle":
            ids = list(plan.task_ids)
            if callback_data.id in ids:
                ids.remove(callback_data.id)
            else:
                ids.append(callback_data.id)
            # Keep the proposal's order.
            plan.task_ids = [i for i in proposed_ids if i in ids]
            proposed = await repo.get_many(proposed_ids)
            await query.message.edit_reply_markup(reply_markup=plan_edit_kb(today, proposed, set(plan.task_ids)))
            await query.answer()
        case "accept":
            chosen = await planning.accept_plan(repo, plan, proposed_ids, today)
            await query.message.edit_text(planning.plan_text(today, chosen))
            await query.answer("Plan accepted 💪")


@router.message(Command("focus"))
async def cmd_focus(message: Message, command: CommandObject, store: SettingsStore, repo: TaskRepo) -> None:
    arg = (command.args or "90").strip().lower()
    if arg in {"off", "stop", "0"}:
        await store.set("focus_until", "")
        await message.answer("🔔 Focus off — reminders are back.")
        return
    if not arg.isdigit() or not 1 <= int(arg) <= 600:
        await message.answer("Usage: <code>/focus 90</code> (minutes) or <code>/focus off</code>")
        return
    until = utcnow() + timedelta(minutes=int(arg))
    await store.set("focus_until", until.isoformat())
    await message.answer(f"🔕 Focus until {until.astimezone(repo.tz):%H:%M}. Reminders will wait.")


@router.message(Command("settings"))
async def cmd_settings(message: Message, store: SettingsStore, repo: TaskRepo) -> None:
    focus = await store.focus_until()
    focus_line = f"until {focus.astimezone(repo.tz):%H:%M}" if focus and focus > utcnow() else "off"
    await message.answer(
        "<b>Settings</b>\n"
        f"Morning brief: {await store.get('morning')}\n"
        f"Evening review: {await store.get('evening')}\n"
        f"Quiet hours: {await store.get('quiet')}\n"
        f"Focus: {focus_line}\n\n"
        "Change with <code>/set morning 07:30</code>, <code>/set evening 21:30</code>, "
        "<code>/set quiet 22:00-08:00</code> or <code>/set quiet off</code>"
    )


@router.message(Command("set"))
async def cmd_set(message: Message, command: CommandObject, store: SettingsStore, scheduler: PlannerScheduler) -> None:
    key, _, value = (command.args or "").strip().partition(" ")
    value = value.strip()
    if key in {"morning", "evening"} and TIME_RE.match(value):
        value = f"{parse_hhmm(value):%H:%M}"
        await store.set(key, value)
        scheduler.set_daily_time(key, parse_hhmm(value))
    elif key == "quiet" and (value == "off" or RANGE_RE.match(value)):
        await store.set(key, value)
    else:
        await message.answer("Usage: <code>/set morning 07:30</code>, <code>/set evening 21:30</code>, <code>/set quiet 22:00-08:00</code>")
        return
    await message.answer(f"Saved: {key} = {value}")

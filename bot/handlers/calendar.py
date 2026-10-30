from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete

from bot import planning
from bot.assistant import Assistant
from bot.calendar_sync import sync_calendar
from bot.db.models import CalendarEvent
from bot.formatting import format_event
from bot.google_calendar import CalendarAuthError, CalendarError, GoogleCalendar
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore
from bot.web import new_oauth_state

router = Router()


class CalCb(CallbackData, prefix="cal"):
    action: str  # sync | disconnect | disconnect_yes


def _connected_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Sync now", callback_data=CalCb(action="sync"))
    b.button(text="🔌 Disconnect", callback_data=CalCb(action="disconnect"))
    return b.as_markup()


async def _overview(repo: TaskRepo, today: date) -> str:
    lines = []
    for label, day in (("Today", today), ("Tomorrow", today + timedelta(days=1))):
        events = await repo.events_on(day)
        lines.append(f"<b>{label} · {day:%a %d.%m}</b>")
        lines += [format_event(e, repo.tz, with_link=True) for e in events] or ["<i>no events</i>"]
        lines.append("")
    return "\n".join(lines).strip()


@router.message(Command("calendar"))
async def cmd_calendar(
    message: Message, repo: TaskRepo, store: SettingsStore, today: date, gcal: GoogleCalendar | None
) -> None:
    if gcal is None:
        await message.answer(
            "Google Calendar isn't configured: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (see README)."
        )
        return
    if not await store.get("google_refresh_token"):
        state = await new_oauth_state(store)
        b = InlineKeyboardBuilder()
        b.button(text="🔗 Connect Google Calendar", url=gcal.auth_url(state))
        await message.answer(
            "Connect Google Calendar so the plan works around your meetings.\n"
            "The bot reads your calendars and only writes events you confirm. The link is valid for 15 minutes.",
            reply_markup=b.as_markup(),
        )
        return
    await message.answer(await _overview(repo, today), reply_markup=_connected_kb(), disable_web_page_preview=True)


@router.callback_query(CalCb.filter())
async def on_calendar(
    query: CallbackQuery,
    callback_data: CalCb,
    repo: TaskRepo,
    store: SettingsStore,
    today: date,
    gcal: GoogleCalendar | None,
) -> None:
    token = await store.get("google_refresh_token")
    if gcal is None or not token:
        await query.answer("Not connected")
        await query.message.edit_reply_markup(reply_markup=None)
        return

    match callback_data.action:
        case "sync":
            try:
                await sync_calendar(repo.session, gcal, token, repo.tz)
            except CalendarAuthError:
                await store.set("google_refresh_token", "")
                await query.message.edit_text("⚠️ Google access was revoked or expired. Use /calendar to reconnect.")
                await query.answer()
                return
            except (CalendarError, OSError, TimeoutError):
                await query.answer("Sync failed, try again later", show_alert=True)
                return
            await repo.session.flush()
            await query.message.edit_text(
                await _overview(repo, today), reply_markup=_connected_kb(), disable_web_page_preview=True
            )
            await query.answer("Synced")
        case "disconnect":
            b = InlineKeyboardBuilder()
            b.button(text="Yes, disconnect", callback_data=CalCb(action="disconnect_yes"))
            await query.message.edit_reply_markup(reply_markup=b.as_markup())
            await query.answer()
        case "disconnect_yes":
            try:
                await gcal.revoke(token)
            except (OSError, TimeoutError):
                pass  # forgetting the token locally is what matters
            await store.set("google_refresh_token", "")
            await repo.session.execute(delete(CalendarEvent))
            await query.message.edit_text("🔌 Google Calendar disconnected and local copies of events deleted.")
            await query.answer()


@router.message(Command("smartplan"))
async def cmd_smartplan(
    message: Message, repo: TaskRepo, store: SettingsStore, today: date, assistant: Assistant | None
) -> None:
    await planning.send_smart_plan(message.bot, message.chat.id, repo, store, assistant, today)

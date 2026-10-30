"""Free-form input: typed text, voice notes and replies to task cards.

With an Anthropic key the message goes to Claude; otherwise (or when the call
fails) the regex parser from phase 1 handles it.
"""

import logging
from datetime import date, datetime, timedelta
from html import escape
from io import BytesIO

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message

from bot import actions as task_actions
from bot import planning
from bot.assistant import (
    Assistant,
    AssistantUnavailable,
    CreateAction,
    EventAction,
    PlanDayAction,
    dump_actions,
    load_actions,
)
from bot.clock import day_bounds_utc, utcnow
from bot.db.models import Task, TaskStatus
from bot.formatting import format_closed, format_task
from bot.google_calendar import CalendarAuthError, CalendarError, GoogleCalendar
from bot.keyboards import ProposalCb, proposal_kb, task_id_from_message, task_kb
from bot.parsing import parse_task
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore
from bot.transcribe import Transcriber

log = logging.getLogger(__name__)
router = Router()

MAX_VOICE_SECONDS = 300
CALENDAR_CONTEXT_DAYS = 7


async def _calendar_context(repo: TaskRepo, store: SettingsStore, today: date):
    """Upcoming events for the prompt, or None when no calendar is connected."""
    if not await store.get("google_refresh_token"):
        return None
    start, _ = day_bounds_utc(today, repo.tz)
    _, end = day_bounds_utc(today + timedelta(days=CALENDAR_CONTEXT_DAYS - 1), repo.tz)
    return await repo.events_between(start, end)


def _reply_card(message: Message) -> Message | None:
    """The bot message this one replies to, if any."""
    original = message.reply_to_message
    if original and original.from_user and original.from_user.is_bot:
        return original
    return None


async def _refresh_card(card: Message, task: Task, today: date) -> None:
    if task.status == TaskStatus.DONE:
        text, markup = format_closed(task, "✅"), None
    elif task.status == TaskStatus.DROPPED:
        text, markup = format_closed(task, "🗑"), None
    else:
        text, markup = format_task(task, today), task_kb(task)
    try:
        await card.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # unchanged or too old to edit


# --- regex fallback ---


async def _regex_capture(message: Message, text: str, repo: TaskRepo, today: date) -> None:
    parsed = parse_task(text, today)
    if not parsed.title:
        await message.reply("That's only a date — what's the task?")
        return
    # A bare time means today.
    due_date = parsed.due_date or (today if parsed.due_time else None)
    task = await repo.create(parsed.title, parsed.priority, due_date, parsed.due_time)
    await message.answer(format_task(task, today), reply_markup=task_kb(task))


async def _regex_edit(message: Message, text: str, card: Message, task: Task, repo: TaskRepo, today: date) -> None:
    parsed = parse_task(text, today)
    await repo.update(task, title=parsed.title or None, priority=parsed.priority)
    if parsed.due_date or parsed.due_time:
        # A bare time keeps the task's day (or pulls an inbox task into today).
        new_date = parsed.due_date or task.due_date or today
        await repo.reschedule(task, new_date, parsed.due_time)
    await _refresh_card(card, task, today)
    await message.reply("✏️ Updated")


# --- AI path ---


async def _with_ai(
    message: Message,
    text: str,
    source: str,
    repo: TaskRepo,
    store: SettingsStore,
    today: date,
    assistant: Assistant,
    card: Message | None,
    reply_task: Task | None,
) -> bool:
    """Returns False when the regex parser should handle the message instead."""
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    tasks = await repo.list_open()
    events = await _calendar_context(repo, store, today)
    try:
        result = await assistant.interpret(text, tasks, datetime.now(repo.tz), reply_task, events)
    except AssistantUnavailable as e:
        log.warning("Assistant unavailable (%s), using the regex parser", e)
        return False
    await repo.log_ai_call(result.model, source, result.input_tokens, result.output_tokens, result.cost_usd)

    by_id = {t.id: t for t in tasks}
    actions = [a for a in result.actions if not hasattr(a, "id") or a.id in by_id]
    if any(isinstance(a, PlanDayAction) for a in actions):
        await planning.send_smart_plan(message.bot, message.chat.id, repo, store, assistant, today)
        actions = [a for a in actions if not isinstance(a, PlanDayAction)]
        if not actions:
            return True
    if events is None:
        actions = [a for a in actions if not isinstance(a, EventAction)]
    if not actions:
        if result.reply:
            await message.reply(escape(result.reply))
            return True
        return False

    # Unambiguous single task actions apply right away; anything else (and every
    # calendar write) gets a preview.
    single = actions[0] if len(actions) == 1 and not isinstance(actions[0], EventAction) else None
    if isinstance(single, CreateAction) and reply_task is None:
        task = await task_actions.apply(repo, single, today)
        await message.answer(format_task(task, today), reply_markup=task_kb(task))
        return True
    if single is not None and reply_task is not None and getattr(single, "id", None) == reply_task.id:
        task = await task_actions.apply(repo, single, today)
        await _refresh_card(card, task, today)
        await message.reply("✏️ Updated")
        return True

    proposal = await repo.create_proposal(dump_actions(actions))
    labels = [task_actions.describe(a, by_id, today) for a in actions]
    await message.answer(
        task_actions.preview_text(actions, by_id, today, result.reply),
        reply_markup=proposal_kb(proposal.id, labels, set(proposal.selected)),
    )
    return True


async def process_text(
    message: Message,
    text: str,
    source: str,
    repo: TaskRepo,
    store: SettingsStore,
    today: date,
    assistant: Assistant | None,
) -> None:
    card = _reply_card(message)
    reply_task = None
    if card is not None:
        task_id = task_id_from_message(card)
        reply_task = await repo.get(task_id) if task_id else None
        if reply_task is None or reply_task.status != TaskStatus.TODO:
            await message.reply("Reply to an open task message to edit it.")
            return

    if assistant is not None and await _with_ai(message, text, source, repo, store, today, assistant, card, reply_task):
        return
    if reply_task is not None:
        await _regex_edit(message, text, card, reply_task, repo, today)
    else:
        await _regex_capture(message, text, repo, today)


# --- handlers ---


@router.message(StateFilter(None), F.voice | F.audio | F.video_note)
async def on_voice(
    message: Message,
    repo: TaskRepo,
    store: SettingsStore,
    today: date,
    assistant: Assistant | None,
    transcriber: Transcriber,
) -> None:
    media = message.voice or message.audio or message.video_note
    if (media.duration or 0) > MAX_VOICE_SECONDS:
        await message.reply("That's a long one — please keep voice notes under 5 minutes.")
        return

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    audio = BytesIO()
    await message.bot.download(media, destination=audio)
    audio.seek(0)
    try:
        text = await transcriber.transcribe(audio)
    except Exception:
        log.exception("Transcription failed")
        await message.reply("Sorry, I couldn't transcribe that.")
        return
    if not text:
        await message.reply("🎙 I couldn't hear any words.")
        return

    await message.reply(f"🎙 <i>{escape(text)}</i>")
    await process_text(message, text, "voice", repo, store, today, assistant)


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_text(
    message: Message, repo: TaskRepo, store: SettingsStore, today: date, assistant: Assistant | None
) -> None:
    await process_text(message, message.text, "text", repo, store, today, assistant)


@router.message(StateFilter(None), F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Unknown command. See /help")


@router.callback_query(ProposalCb.filter())
async def on_proposal(
    query: CallbackQuery,
    callback_data: ProposalCb,
    repo: TaskRepo,
    store: SettingsStore,
    today: date,
    gcal: GoogleCalendar | None,
) -> None:
    proposal = await repo.get_proposal(callback_data.id)
    if proposal is None or proposal.resolved_at is not None:
        await query.answer("Already handled")
        await query.message.edit_reply_markup(reply_markup=None)
        return

    actions = load_actions(proposal.actions)
    tasks = await repo.get_many([a.id for a in actions if hasattr(a, "id")])
    by_id = {t.id: t for t in tasks}
    # Describe before applying: applying renames tasks.
    labels = [task_actions.describe(a, by_id, today) for a in actions]

    match callback_data.action:
        case "toggle":
            selected = set(proposal.selected) ^ {callback_data.idx}
            proposal.selected = sorted(selected)
            await query.message.edit_reply_markup(reply_markup=proposal_kb(proposal.id, labels, selected))
            await query.answer()
        case "cancel":
            proposal.resolved_at = utcnow()
            await query.message.edit_text("✖️ Cancelled — nothing saved.")
            await query.answer()
        case "save":
            proposal.resolved_at = utcnow()
            lines = []
            token = await store.get("google_refresh_token")
            for idx in proposal.selected:
                action = actions[idx]
                if isinstance(action, EventAction):
                    lines.append(escape(await _save_event(gcal, token, action, repo, labels[idx])))
                    continue
                task = await task_actions.apply(repo, action, today)
                prefix = "" if task else "⚠️ skipped (task closed): "
                lines.append(escape(prefix + labels[idx]))
            text = "💾 <b>Saved</b>\n" + "\n".join(lines) if lines else "Nothing selected — nothing saved."
            await query.message.edit_text(text)
            await query.answer("Saved")


async def _save_event(gcal: GoogleCalendar | None, token: str, action: EventAction, repo: TaskRepo, label: str) -> str:
    if gcal is None or not token:
        return f"⚠️ calendar not connected: {label}"
    try:
        await task_actions.create_event(gcal, token, action, repo.tz)
    except CalendarAuthError:
        return f"⚠️ calendar access expired, /calendar to reconnect: {label}"
    except (CalendarError, OSError, TimeoutError):
        log.exception("Creating a calendar event failed")
        return f"⚠️ couldn't create: {label}"
    return label + " (added to Google Calendar)"

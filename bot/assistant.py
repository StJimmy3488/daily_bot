"""Free text (typed or transcribed) -> proposed task actions, via Claude.

One request per message: the open tasks go into the prompt, Claude answers with
text and/or tool calls. Tool calls are *proposals* - nothing is written until
the bot (or the user, via the preview) applies them.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Annotated, Literal

import anthropic
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from bot.db.models import Task

log = logging.getLogger(__name__)

# USD per 1M tokens (input, output), for the cost log.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

MAX_TASKS_IN_PROMPT = 200

SYSTEM_PROMPT = """You are the language understanding engine of a personal planner Telegram bot. \
It has a single user, who writes or dictates (usually in Russian or English) things to do, \
reminders, changes to existing tasks, or questions about their tasks. Voice messages arrive \
as automatic transcripts and may contain recognition errors.

Turn each message into tool calls:
- create_task for every new task or reminder in the message (a brain dump can hold several). \
A reminder is a task with a time. "Remind me in 20 minutes" means the current date and time \
plus 20 minutes; roll over to the next day when needed.
- update_task, complete_task or drop_task for changes to the existing tasks listed in the \
context, referring to them by id. Only touch a task when it is clear which one the user means. \
When the context says the user is replying to a task, the message is about that task.
- When the user asks a question about their tasks, answer it in a short text reply in the \
user's language, using only the task list.

Rules:
- Titles are short and imperative, in the user's language, without the date or time words.
- Resolve relative dates against the current date in the context. A bare weekday means its \
next occurrence after today.
- Leave the date empty when no day is implied; the task then goes to the inbox.
- Priority 1 only when the user signals urgency or importance, 3 for "someday" or "low \
priority", otherwise 2.
- Never invent tasks the user did not mention.
- If the message is too unclear to act on, ask one short clarifying question instead of \
calling tools.
- Do not restate the actions in text; the bot shows its own preview."""

_DATE_HELP = "YYYY-MM-DD"

TOOLS = [
    {
        "name": "create_task",
        "description": "Create a new task or reminder.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short imperative title."},
                "date": {"type": "string", "description": f"Due date as {_DATE_HELP}, or empty string for the inbox."},
                "time": {"type": "string", "description": "Time as HH:MM (24h), or empty string when none."},
                "priority": {"type": "integer", "enum": [1, 2, 3], "description": "1 high, 2 normal, 3 low."},
            },
            "required": ["title", "date", "time", "priority"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_task",
        "description": "Change an existing task. Empty string or 0 means leave that field unchanged.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string", "description": "New title, or empty string to keep it."},
                "date": {
                    "type": "string",
                    "description": f"New due date as {_DATE_HELP}, 'inbox' to unschedule, or empty string to keep it.",
                },
                "time": {"type": "string", "description": "New time as HH:MM, or empty string to keep it."},
                "priority": {"type": "integer", "enum": [0, 1, 2, 3], "description": "New priority, or 0 to keep it."},
            },
            "required": ["id", "title", "date", "time", "priority"],
            "additionalProperties": False,
        },
    },
    {
        "name": "complete_task",
        "description": "Mark an existing task as done.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drop_task",
        "description": "Drop (cancel) an existing task the user no longer wants to do.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


# --- actions ---


class CreateAction(BaseModel):
    kind: Literal["create"] = "create"
    title: str = Field(min_length=1)
    due_date: date | None = None
    due_time: time | None = None
    priority: int = Field(default=2, ge=1, le=3)


class UpdateAction(BaseModel):
    kind: Literal["update"] = "update"
    id: int
    title: str | None = None
    due_date: date | None = None
    unschedule: bool = False
    due_time: time | None = None
    priority: int | None = Field(default=None, ge=1, le=3)


class CompleteAction(BaseModel):
    kind: Literal["complete"] = "complete"
    id: int


class DropAction(BaseModel):
    kind: Literal["drop"] = "drop"
    id: int


Action = Annotated[CreateAction | UpdateAction | CompleteAction | DropAction, Field(discriminator="kind")]
ACTIONS = TypeAdapter(list[Action])


def _opt_date(value: str) -> date | None:
    return date.fromisoformat(value) if value.strip() else None


def _opt_time(value: str) -> time | None:
    return time.fromisoformat(value.strip()) if value.strip() else None


def action_from_tool(name: str, data: dict) -> Action:
    """Validate a tool call. Raises ValueError on anything malformed."""
    try:
        match name:
            case "create_task":
                return CreateAction(
                    title=data["title"].strip(),
                    due_date=_opt_date(data["date"]),
                    due_time=_opt_time(data["time"]),
                    priority=data["priority"],
                )
            case "update_task":
                raw_date = data["date"].strip()
                return UpdateAction(
                    id=data["id"],
                    title=data["title"].strip() or None,
                    unschedule=raw_date.lower() == "inbox",
                    due_date=None if raw_date.lower() == "inbox" else _opt_date(raw_date),
                    due_time=_opt_time(data["time"]),
                    priority=data["priority"] or None,
                )
            case "complete_task":
                return CompleteAction(id=data["id"])
            case "drop_task":
                return DropAction(id=data["id"])
    except (KeyError, TypeError, ValueError, ValidationError) as e:
        raise ValueError(f"bad {name} input {data!r}: {e}") from e
    raise ValueError(f"unknown tool {name}")


def dump_actions(actions: list[Action]) -> list[dict]:
    return ACTIONS.dump_python(actions, mode="json")


def load_actions(data: list[dict]) -> list[Action]:
    return ACTIONS.validate_python(data)


# --- the call ---


class AssistantUnavailable(Exception):
    """Claude couldn't be used for this message; the caller falls back to the regex parser."""


@dataclass
class Interpretation:
    reply: str
    actions: list[Action] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICES.get(self.model, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


def build_context(tasks: list[Task], now: datetime, reply_to: Task | None) -> str:
    lines = [f"Now: {now:%A %Y-%m-%d %H:%M}, timezone {now.tzinfo}", ""]
    lines.append("Open tasks (id | title | date | time | priority):")
    for t in tasks[:MAX_TASKS_IN_PROMPT]:
        due = t.due_date.isoformat() if t.due_date else "inbox"
        at = f"{t.due_time:%H:%M}" if t.due_time else "-"
        lines.append(f"{t.id} | {t.title} | {due} | {at} | {t.priority}")
    if not tasks:
        lines.append("(none)")
    if reply_to is not None:
        lines += ["", f"The user is replying to task {reply_to.id}."]
    return "\n".join(lines)


class Assistant:
    def __init__(self, api_key: str, model: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0, max_retries=1)
        self.model = model

    async def interpret(self, text: str, tasks: list[Task], now: datetime, reply_to: Task | None = None) -> Interpretation:
        content = f"{build_context(tasks, now, reply_to)}\n\nMessage:\n{text}"
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.RateLimitError as e:
            raise AssistantUnavailable("rate limited") from e
        except anthropic.APIStatusError as e:
            log.warning("Claude API error %s: %s", e.status_code, e.message)
            raise AssistantUnavailable(f"API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise AssistantUnavailable("connection error") from e

        result = Interpretation(
            reply="",
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            raise AssistantUnavailable("refusal")

        texts = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                try:
                    result.actions.append(action_from_tool(block.name, block.input))
                except ValueError:
                    log.warning("Skipping invalid tool call", exc_info=True)
        result.reply = "\n".join(texts).strip()
        return result

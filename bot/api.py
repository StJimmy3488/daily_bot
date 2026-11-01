"""JSON API for the Telegram Mini App.

Every request carries Telegram's signed `initData` (`Authorization: tma <initData>`);
only the owner gets through. All writes go through TaskRepo, so reminders, the
events log and recurring tasks behave exactly like in the chat.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Annotated

from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from bot import planning
from bot.clock import as_utc, local_today
from bot.db.models import CalendarEvent, Task, TaskStatus
from bot.recurrence import describe_rule, first_occurrence, normalize_rule
from bot.repo import TaskRepo
from bot.settings_store import SettingsStore

INIT_DATA_MAX_AGE = timedelta(days=1)


@dataclass
class ApiContext:
    repo: TaskRepo
    store: SettingsStore
    today: date


# --- auth & session ---


def check_init_data(authorization: str, bot_token: str, owner_id: int) -> None:
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != "tma" or not init_data:
        raise HTTPException(401, "Missing Telegram init data")
    try:
        data = safe_parse_webapp_init_data(bot_token, init_data)
    except ValueError as e:
        raise HTTPException(401, "Invalid Telegram init data") from e
    if datetime.now(data.auth_date.tzinfo) - data.auth_date > INIT_DATA_MAX_AGE:
        raise HTTPException(401, "Telegram init data expired, reopen the app")
    if data.user is None or data.user.id != owner_id:
        raise HTTPException(403, "Not your planner")


async def context(request: Request, authorization: Annotated[str, Header()] = "") -> AsyncIterator[ApiContext]:
    state = request.app.state
    check_init_data(authorization, state.bot_token, state.owner_id)
    session: AsyncSession
    async with state.sessionmaker() as session, session.begin():
        yield ApiContext(TaskRepo(session, state.tz), SettingsStore(session), local_today(state.tz))


Ctx = Annotated[ApiContext, Depends(context)]


# --- schemas ---


class TaskOut(BaseModel):
    id: int
    title: str
    notes: str | None
    status: str
    priority: int
    due_date: date | None
    due_time: str | None  # "HH:MM", local
    est_minutes: int | None
    recurrence_rule: str | None
    repeat_label: str | None


class EventOut(BaseModel):
    id: int
    title: str
    start: str  # local "YYYY-MM-DDTHH:MM"
    end: str
    all_day: bool
    link: str | None


class DayOut(BaseModel):
    date: date
    tasks: list[TaskOut]
    events: list[EventOut]


class DayViewOut(DayOut):
    overdue: list[TaskOut]


class WeekOut(BaseModel):
    start: date
    days: list[DayOut]


class MetaOut(BaseModel):
    today: date
    timezone: str
    work_hours: tuple[str, str]
    ai: bool
    calendar: bool


class _TaskFields(BaseModel):
    @field_validator("title", check_fields=False)
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("title can't be empty")
        return v

    @field_validator("recurrence_rule", check_fields=False)
    @classmethod
    def _rule(cls, v: str | None) -> str | None:
        return normalize_rule(v) if v else None


class TaskCreate(_TaskFields):
    title: str = Field(max_length=500)
    due_date: date | None = None
    due_time: time | None = None
    priority: int = Field(default=2, ge=1, le=3)
    est_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    recurrence_rule: str | None = None


class TaskPatch(_TaskFields):
    """Only the fields that are sent are changed; send null to clear date, time, estimate or repeat."""

    title: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5000)
    due_date: date | None = None
    due_time: time | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    est_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    recurrence_rule: str | None = None


class ClosedOut(BaseModel):
    task: TaskOut
    next: TaskOut | None  # the new occurrence of a recurring task


class PlanBlockOut(BaseModel):
    start: str  # "HH:MM"
    end: str
    title: str
    task_id: int | None
    fixed: bool  # meeting or task with its own time


class PlanOut(BaseModel):
    date: date
    blocks: list[PlanBlockOut]
    unplaced: list[TaskOut]
    note: str


class PlanApplyItem(BaseModel):
    task_id: int
    time: time


class PlanApply(BaseModel):
    date: date
    items: list[PlanApplyItem]


def task_out(t: Task) -> TaskOut:
    return TaskOut(
        id=t.id,
        title=t.title,
        notes=t.notes,
        status=t.status,
        priority=t.priority,
        due_date=t.due_date,
        due_time=f"{t.due_time:%H:%M}" if t.due_time else None,
        est_minutes=t.est_minutes,
        recurrence_rule=t.recurrence_rule,
        repeat_label=describe_rule(t.recurrence_rule) if t.recurrence_rule else None,
    )


def event_out(e: CalendarEvent, tz) -> EventOut:
    start, end = as_utc(e.start_at).astimezone(tz), as_utc(e.end_at).astimezone(tz)
    return EventOut(
        id=e.id,
        title=e.title,
        start=f"{start:%Y-%m-%dT%H:%M}",
        end=f"{end:%Y-%m-%dT%H:%M}",
        all_day=e.all_day,
        link=e.link,
    )


async def _open_task(ctx: ApiContext, task_id: int) -> Task:
    task = await ctx.repo.get(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.status != TaskStatus.TODO:
        raise HTTPException(409, "Task is already closed")
    return task


# --- routes ---

router = APIRouter(prefix="/api")


@router.get("/meta")
async def meta(ctx: Ctx, request: Request) -> MetaOut:
    start, end = await ctx.store.work_hours()
    return MetaOut(
        today=ctx.today,
        timezone=str(ctx.repo.tz),
        work_hours=(f"{start:%H:%M}", f"{end:%H:%M}"),
        ai=request.app.state.assistant is not None,
        calendar=bool(await ctx.store.get("google_refresh_token")),
    )


@router.get("/day")
async def day_view(ctx: Ctx, day: Annotated[date | None, "YYYY-MM-DD"] = None) -> DayViewOut:
    day = day or ctx.today
    tz = ctx.repo.tz
    return DayViewOut(
        date=day,
        tasks=[task_out(t) for t in await ctx.repo.tasks_between(day, day)],
        events=[event_out(e, tz) for e in await ctx.repo.events_on(day)],
        overdue=[task_out(t) for t in await ctx.repo.overdue(ctx.today)] if day == ctx.today else [],
    )


@router.get("/week")
async def week_view(ctx: Ctx, start: date | None = None) -> WeekOut:
    start = start or ctx.today  # seven days from `start` (the app shows a rolling week from today)
    end = start + timedelta(days=6)
    tasks = await ctx.repo.tasks_between(start, end)
    tz = ctx.repo.tz
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        days.append(
            DayOut(
                date=d,
                tasks=[task_out(t) for t in tasks if t.due_date == d],
                events=[event_out(e, tz) for e in await ctx.repo.events_on(d)],
            )
        )
    return WeekOut(start=start, days=days)


@router.get("/inbox")
async def inbox(ctx: Ctx) -> list[TaskOut]:
    return [task_out(t) for t in await ctx.repo.list_inbox()]


@router.post("/tasks", status_code=201)
async def create_task(ctx: Ctx, body: TaskCreate) -> TaskOut:
    due_date = body.due_date or (ctx.today if body.due_time else None)
    if body.recurrence_rule and due_date is None:
        due_date = first_occurrence(body.recurrence_rule, ctx.today)
    task = await ctx.repo.create(
        body.title, body.priority, due_date, body.due_time, body.recurrence_rule, body.est_minutes
    )
    return task_out(task)


@router.patch("/tasks/{task_id}")
async def update_task(ctx: Ctx, task_id: int, body: TaskPatch) -> TaskOut:
    task = await _open_task(ctx, task_id)
    sent = body.model_fields_set

    stop_repeating = "recurrence_rule" in sent and body.recurrence_rule is None
    await ctx.repo.update(
        task,
        title=body.title if "title" in sent else None,
        priority=body.priority if "priority" in sent else None,
        recurrence_rule=body.recurrence_rule if "recurrence_rule" in sent else None,
        stop_repeating=stop_repeating,
    )
    if "notes" in sent:
        task.notes = body.notes or None
    if "est_minutes" in sent:
        task.est_minutes = body.est_minutes

    if "due_date" in sent or "due_time" in sent:
        new_date = body.due_date if "due_date" in sent else task.due_date
        if "due_time" in sent and body.due_time is not None and new_date is None:
            new_date = ctx.today  # a time without a day means today
        clear_time = ("due_time" in sent and body.due_time is None) or new_date is None
        await ctx.repo.reschedule(task, new_date, body.due_time if "due_time" in sent else None, clear_time)
    return task_out(task)


@router.post("/tasks/{task_id}/complete")
async def complete_task(ctx: Ctx, task_id: int) -> ClosedOut:
    task = await _open_task(ctx, task_id)
    nxt = await ctx.repo.complete(task)
    return ClosedOut(task=task_out(task), next=task_out(nxt) if nxt else None)


@router.post("/tasks/{task_id}/drop")
async def drop_task(ctx: Ctx, task_id: int) -> ClosedOut:
    task = await _open_task(ctx, task_id)
    nxt = await ctx.repo.drop(task)
    return ClosedOut(task=task_out(task), next=task_out(nxt) if nxt else None)


@router.post("/tasks/{task_id}/reopen")
async def reopen_task(ctx: Ctx, task_id: int) -> TaskOut:
    """Undo for an accidental tick."""
    task = await ctx.repo.get(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.status != TaskStatus.TODO:
        try:
            await ctx.repo.reopen(task)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    return task_out(task)


@router.post("/plan")
async def smart_plan(ctx: Ctx, request: Request, day: date | None = None) -> PlanOut:
    day = day or ctx.today
    plan, note, _ = await planning.compute_smart_plan(ctx.repo, ctx.store, request.app.state.assistant, day)
    return PlanOut(
        date=day,
        blocks=[
            PlanBlockOut(
                start=f"{b.start:%H:%M}",
                end=f"{b.end:%H:%M}",
                title=b.title,
                task_id=b.task.id if b.task else None,
                fixed=b.task is None or b.task.due_time is not None,
            )
            for b in plan.blocks
        ],
        unplaced=[task_out(t) for t in plan.unplaced],
        note=note,
    )


@router.post("/plan/apply")
async def apply_plan(ctx: Ctx, body: PlanApply) -> list[TaskOut]:
    """Give each planned task its slot's start time (which also schedules its reminder)."""
    updated = []
    for item in body.items:
        task = await ctx.repo.get(item.task_id)
        if task is None or task.status != TaskStatus.TODO:
            continue
        await ctx.repo.reschedule(task, body.date, item.time)
        updated.append(task_out(task))
    return updated

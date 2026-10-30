"""Fit today's tasks into the free time between meetings, inside work hours.

The ordering and duration estimates can come from Claude; the placement is
always done here, so a task can never land on top of a meeting.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from bot.clock import as_utc
from bot.db.models import CalendarEvent, Task

DEFAULT_MINUTES = 30
TIMED_TASK_MINUTES = 15
STEP = timedelta(minutes=5)


@dataclass
class Block:
    start: datetime  # local
    end: datetime
    title: str
    task: Task | None = None  # None for meetings

    @property
    def is_meeting(self) -> bool:
        return self.task is None


@dataclass
class DayPlanResult:
    blocks: list[Block]  # meetings + placed tasks, chronological
    unplaced: list[Task]
    note: str = ""


def _round_up(dt: datetime) -> datetime:
    minutes = (dt.minute // 5 + (1 if dt.minute % 5 or dt.second or dt.microsecond else 0)) * 5
    return dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)


def _free_gaps(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    gaps, cursor = [], start
    for b_start, b_end in sorted(busy):
        if b_end <= cursor:
            continue
        if b_start > cursor:
            gaps.append((cursor, min(b_start, end)))
        cursor = max(cursor, b_end)
        if cursor >= end:
            break
    if cursor < end:
        gaps.append((cursor, end))
    return [(s, e) for s, e in gaps if e > s]


def fit_day(
    day: date,
    tasks: list[Task],
    minutes: dict[int, int],
    events: list[CalendarEvent],
    work: tuple[time, time],
    tz: ZoneInfo,
    now: datetime,
) -> DayPlanResult:
    """Place `tasks` in the given order. Tasks with a fixed time stay at their time."""
    day_start = datetime.combine(day, work[0], tzinfo=tz)
    day_end = datetime.combine(day, work[1], tzinfo=tz)
    if now.astimezone(tz).date() == day:
        day_start = max(day_start, _round_up(now.astimezone(tz)))

    blocks: list[Block] = []
    busy: list[tuple[datetime, datetime]] = []
    for e in events:
        if e.all_day or not e.busy:
            continue
        start, end = as_utc(e.start_at).astimezone(tz), as_utc(e.end_at).astimezone(tz)
        blocks.append(Block(start, end, e.title))
        busy.append((start, end))

    flexible = []
    for task in tasks:
        if task.due_time and task.due_date == day:
            start = datetime.combine(day, task.due_time, tzinfo=tz)
            end = start + timedelta(minutes=task.est_minutes or TIMED_TASK_MINUTES)
            blocks.append(Block(start, end, task.title, task))
            busy.append((start, end))
        else:
            flexible.append(task)

    unplaced = []
    for task in flexible:
        need = timedelta(minutes=minutes.get(task.id) or task.est_minutes or DEFAULT_MINUTES)
        slot = next(((s, s + need) for s, e in _free_gaps(day_start, day_end, busy) if e - s >= need), None)
        if slot is None:
            unplaced.append(task)
            continue
        blocks.append(Block(slot[0], slot[1], task.title, task))
        busy.append(slot)

    blocks.sort(key=lambda b: b.start)
    return DayPlanResult(blocks=blocks, unplaced=unplaced)


def default_order(tasks: list[Task]) -> list[Task]:
    """Without AI: by priority, oldest due date first."""
    return sorted(tasks, key=lambda t: (t.priority, t.due_date or date.max, t.id))

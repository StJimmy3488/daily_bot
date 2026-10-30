from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from bot.clock import utcnow


class Base(DeclarativeBase):
    pass


class TaskStatus(StrEnum):
    TODO = "todo"
    DONE = "done"
    DROPPED = "dropped"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    color: Mapped[str | None] = mapped_column(String(16))
    archived: Mapped[bool] = mapped_column(default=False)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_status_due", "status", "due_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.TODO)
    # 1 = high, 2 = normal, 3 = low
    priority: Mapped[int] = mapped_column(SmallInteger, default=2)
    # NULL due_date means the task is in the inbox
    due_date: Mapped[date | None] = mapped_column(Date)
    due_time: Mapped[time | None] = mapped_column(Time)
    est_minutes: Mapped[int | None]
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    # RFC 5545 RRULE, e.g. FREQ=WEEKLY;BYDAY=MO. Completing spawns the next occurrence.
    recurrence_rule: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DayPlan(Base):
    __tablename__ = "day_plans"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    task_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # NULL while the morning brief is still a proposal
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Event(Base):
    """Append-only log of task changes; powers stats and slip counting."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AiCall(Base):
    """Per-call cost log for the LLM."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Float)


class AiProposal(Base):
    """Actions parsed by the LLM, waiting for the user to confirm them."""

    __tablename__ = "ai_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    actions: Mapped[list[dict]] = mapped_column(JSON)
    selected: Mapped[list[int]] = mapped_column(JSON)  # indexes into actions
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarEvent(Base):
    """Mirror of Google Calendar events in a rolling window, refreshed every 15 minutes."""

    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("calendar_id", "event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_id: Mapped[str] = mapped_column(String(255))
    event_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    # False for events marked "free" in Google; those don't block the smart plan.
    busy: Mapped[bool] = mapped_column(Boolean, default=True)
    link: Mapped[str | None] = mapped_column(Text)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

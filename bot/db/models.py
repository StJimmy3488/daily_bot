from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, SmallInteger, String, Text, Time
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

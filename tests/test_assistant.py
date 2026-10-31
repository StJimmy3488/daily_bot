import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from bot import actions as task_actions
from bot.assistant import (
    Assistant,
    CompleteAction,
    CreateAction,
    EventAction,
    PlanDayAction,
    UpdateAction,
    action_from_tool,
    build_context,
    dump_actions,
    load_actions,
)
from bot.db.models import TaskStatus
from tests.conftest import TZ

TODAY = date(2026, 10, 29)


def test_action_from_tool_create_and_update():
    a = action_from_tool(
        "create_task", {"title": " Call mom ", "date": "2026-10-30", "time": "19:00", "priority": 2, "repeat": ""}
    )
    assert a == CreateAction(title="Call mom", due_date=date(2026, 10, 30), due_time=time(19), priority=2)

    u = action_from_tool(
        "update_task", {"id": 5, "title": "", "date": "inbox", "time": "", "priority": 0, "repeat": ""}
    )
    assert u == UpdateAction(id=5, unschedule=True)

    r = action_from_tool(
        "create_task",
        {"title": "Rent", "date": "", "time": "", "priority": 2, "repeat": "rrule:freq=monthly;bymonthday=1"},
    )
    assert r.recurrence == "FREQ=MONTHLY;BYMONTHDAY=1"

    stop = action_from_tool(
        "update_task", {"id": 5, "title": "", "date": "", "time": "", "priority": 0, "repeat": "none"}
    )
    assert stop.stop_repeating and stop.recurrence is None

    e = action_from_tool(
        "create_calendar_event", {"title": "Audit", "date": "2026-10-30", "start": "10:00", "minutes": 120}
    )
    assert e == EventAction(title="Audit", day=date(2026, 10, 30), start=time(10), minutes=120)
    assert action_from_tool("plan_day", {}) == PlanDayAction()


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("create_task", {"title": "  ", "date": "", "time": "", "priority": 2, "repeat": ""}),
        ("create_task", {"title": "x", "date": "tomorrow", "time": "", "priority": 2, "repeat": ""}),
        ("create_task", {"title": "x", "date": "", "time": "25:00", "priority": 2, "repeat": ""}),
        ("create_task", {"title": "x", "date": "", "time": "", "priority": 2, "repeat": "every monday"}),
        ("create_calendar_event", {"title": "x", "date": "2026-10-30", "start": "10:00", "minutes": 0}),
        ("update_task", {"id": 1}),
        ("rm_rf", {}),
    ],
)
def test_action_from_tool_rejects_bad_input(name, data):
    with pytest.raises(ValueError):
        action_from_tool(name, data)


def test_actions_roundtrip_json():
    actions = [CreateAction(title="a", due_date=TODAY, due_time=time(9)), CompleteAction(id=3)]
    assert load_actions(dump_actions(actions)) == actions


async def test_build_context(repo):
    t = await repo.create("Dentist", due_date=TODAY, due_time=time(14, 30))
    await repo.create("Inbox thing")
    ctx = build_context(await repo.list_open(), datetime(2026, 10, 29, 9, 0, tzinfo=TZ), reply_to=t)
    assert "Now: Thursday 2026-10-29 09:00, timezone Europe/Riga" in ctx
    assert f"{t.id} | Dentist | 2026-10-29 | 14:30 | 2 | -" in ctx
    assert "| Inbox thing | inbox | - |" in ctx
    assert f"replying to task {t.id}" in ctx


async def test_apply_actions(repo):
    task = await repo.create("Dentist", due_date=TODAY, due_time=time(14))
    other = await repo.create("Old")

    created = await task_actions.apply(repo, CreateAction(title="Gym", due_time=time(18)), TODAY)
    assert created.due_date == TODAY  # bare time -> today

    await task_actions.apply(repo, UpdateAction(id=task.id, due_date=TODAY + timedelta(days=1)), TODAY)
    assert task.due_date == TODAY + timedelta(days=1) and task.due_time == time(14)

    await task_actions.apply(repo, UpdateAction(id=task.id, due_time=time(9)), TODAY)
    assert task.due_date == TODAY + timedelta(days=1) and task.due_time == time(9)  # bare time keeps the day

    await task_actions.apply(repo, CompleteAction(id=other.id), TODAY)
    assert other.status == TaskStatus.DONE
    assert await task_actions.apply(repo, CompleteAction(id=other.id), TODAY) is None  # already closed


def test_describe():
    tasks = {7: SimpleNamespace(title="Dentist", due_date=TODAY)}
    assert (
        task_actions.describe(CreateAction(title="Gym", due_date=TODAY, due_time=time(18)), {}, TODAY)
        == "➕ Gym · today 18:00"
    )
    assert (
        task_actions.describe(UpdateAction(id=7, due_date=TODAY + timedelta(days=1)), tasks, TODAY)
        == "✏️ Dentist: → tomorrow"
    )
    assert task_actions.describe(CompleteAction(id=8), tasks, TODAY) == "✅ #8 (missing)"


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


async def test_interpret_parses_tool_calls_and_cost():
    response = SimpleNamespace(
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Got it."),
            SimpleNamespace(
                type="tool_use",
                name="create_task",
                input={"title": "Buy milk", "date": "", "time": "", "priority": 2, "repeat": ""},
            ),
            SimpleNamespace(
                type="tool_use",
                name="create_task",
                input={"title": "bad", "date": "nope", "time": "", "priority": 2, "repeat": ""},
            ),
            SimpleNamespace(type="tool_use", name="complete_task", input={"id": 4}),
        ],
    )
    assistant = Assistant("test-key", "claude-haiku-5-5", "claude-opus-5-5")
    assistant.client = SimpleNamespace(messages=FakeMessages(response))

    result = await assistant.interpret("buy milk, and I did the report", [], datetime(2026, 10, 29, 9, tzinfo=TZ))

    assert result.reply == "Got it."
    assert result.actions == [CreateAction(title="Buy milk"), CompleteAction(id=4)]  # invalid call skipped
    assert result.cost_usd == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1_000_000)
    sent = assistant.client.messages.kwargs
    assert sent["model"] == "claude-haiku-5-5"
    assert all(tool["strict"] for tool in sent["tools"])
    assert "tool_choice" not in sent
    assert "create_calendar_event" not in {t["name"] for t in sent["tools"]}  # no calendar connected


async def test_order_day_uses_fallbacks_on_opus_and_fills_gaps(repo):
    a = await repo.create("Report", priority=1, due_date=TODAY)
    b = await repo.create("Email", due_date=TODAY)
    c = await repo.create("Errand", due_date=TODAY)
    response = SimpleNamespace(
        stop_reason="end_turn",
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=500, output_tokens=100),
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "order": [
                            {"id": b.id, "minutes": 999},
                            {"id": 12345, "minutes": 5},
                            {"id": a.id, "minutes": 60},
                        ],
                        "note": "Go",
                    }
                ),
            )
        ],
    )
    fake = FakeMessages(response)
    assistant = Assistant("test-key", "claude-haiku-5-5", "claude-opus-5-5")
    assistant.client = SimpleNamespace(beta=SimpleNamespace(messages=fake))

    order = await assistant.order_day([a, b, c], [], (time(9), time(18)), datetime(2026, 10, 29, 8, tzinfo=TZ))

    assert order.ids == [b.id, a.id, c.id]  # unknown id dropped, missing one appended
    assert order.minutes == {b.id: 240, a.id: 60}  # clamped
    assert order.note == "Go"
    assert fake.kwargs["fallbacks"] == "default"
    assert fake.kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert fake.kwargs["output_config"]["format"]["type"] == "json_schema"

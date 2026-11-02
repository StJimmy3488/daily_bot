import time as clock
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.clock import local_today
from bot.db.models import Reminder
from bot.dev_init_data import sign_init_data
from bot.web import create_app
from tests.conftest import TZ

TOKEN = "123456:TEST-token"
OWNER = 4242


@pytest.fixture
async def api(session):
    # Requests share the test's connection; each request's transaction becomes a savepoint.
    maker = async_sessionmaker(bind=session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    app = create_app(None, maker, OWNER, None, None, bot_token=TOKEN, tz=TZ, assistant=None)
    headers = {"Authorization": f"tma {sign_init_data(TOKEN, OWNER)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=headers) as c:
        yield c


@pytest.mark.parametrize(
    ("auth", "status"),
    [
        (None, 401),
        ("Bearer x", 401),
        (f"tma {sign_init_data(TOKEN, 999)}", 403),  # someone else
        (f"tma {sign_init_data('654321:other-bot', OWNER)}", 401),  # signed by another bot
        (f"tma {sign_init_data(TOKEN, OWNER, auth_date=int(clock.time()) - 2 * 86400)}", 401),  # expired
        (f"tma {sign_init_data(TOKEN, OWNER).replace('Dev', 'Eve')}", 401),  # tampered
    ],
)
async def test_auth_rejects(api, auth, status):
    headers = {"Authorization": auth} if auth else {}
    r = await api.get("/api/inbox", headers=headers if auth else {"Authorization": ""})
    assert r.status_code == status


async def test_task_lifecycle(api, session):
    today = local_today(TZ)
    r = await api.post("/api/tasks", json={"title": "  Write report ", "priority": 1})
    assert r.status_code == 201
    task = r.json()
    assert task["title"] == "Write report" and task["due_date"] is None

    assert [t["id"] for t in (await api.get("/api/inbox")).json()] == [task["id"]]

    tomorrow = (today + timedelta(days=1)).isoformat()
    r = await api.patch(f"/api/tasks/{task['id']}", json={"due_date": tomorrow, "due_time": "10:30"})
    assert r.json()["due_date"] == tomorrow and r.json()["due_time"] == "10:30"
    reminders = list(await session.scalars(select(Reminder).where(Reminder.task_id == task["id"])))
    assert len(reminders) == 1  # same reminder logic as the chat

    r = await api.patch(f"/api/tasks/{task['id']}", json={"due_time": None})
    assert r.json()["due_time"] is None and r.json()["due_date"] == tomorrow

    r = await api.patch(f"/api/tasks/{task['id']}", json={"title": "Report v2"})  # untouched fields stay
    assert r.json()["title"] == "Report v2" and r.json()["priority"] == 1 and r.json()["due_date"] == tomorrow

    day = (await api.get("/api/day", params={"day": tomorrow})).json()
    assert [t["title"] for t in day["tasks"]] == ["Report v2"] and day["overdue"] == []

    r = await api.post(f"/api/tasks/{task['id']}/complete")
    assert r.json()["task"]["status"] == "done" and r.json()["next"] is None
    assert (await api.post(f"/api/tasks/{task['id']}/complete")).status_code == 409
    assert (await api.post(f"/api/tasks/{task['id']}/reopen")).json()["status"] == "todo"


async def test_recurring_and_validation(api):
    today = local_today(TZ)
    r = await api.post(
        "/api/tasks", json={"title": "Water plants", "due_date": today.isoformat(), "recurrence_rule": "freq=daily"}
    )
    task = r.json()
    assert task["recurrence_rule"] == "FREQ=DAILY" and task["repeat_label"] == "daily"

    closed = (await api.post(f"/api/tasks/{task['id']}/complete")).json()
    assert closed["next"]["due_date"] == (today + timedelta(days=1)).isoformat()
    assert (await api.post(f"/api/tasks/{task['id']}/reopen")).status_code == 409  # next one already exists

    for bad in [{"title": "  "}, {"title": "x", "priority": 5}, {"title": "x", "recurrence_rule": "every day"}]:
        assert (await api.post("/api/tasks", json=bad)).status_code == 422
    assert (await api.patch("/api/tasks/999999", json={"title": "x"})).status_code == 404


async def test_week_and_overdue(api):
    today = local_today(TZ)
    monday = today - timedelta(days=today.weekday())
    await api.post("/api/tasks", json={"title": "Old", "due_date": (today - timedelta(days=9)).isoformat()})
    await api.post("/api/tasks", json={"title": "Mon", "due_date": monday.isoformat()})

    week = (await api.get("/api/week", params={"start": monday.isoformat()})).json()
    assert week["start"] == monday.isoformat() and len(week["days"]) == 7
    assert [t["title"] for t in week["days"][0]["tasks"]] == ["Mon"]
    rolling = (await api.get("/api/week")).json()
    assert rolling["start"] == today.isoformat()

    day = (await api.get("/api/day")).json()
    expected = ["Old", "Mon"] if monday < today else ["Old"]  # this week's Monday is overdue later in the week
    assert [t["title"] for t in day["overdue"]] == expected


async def test_smart_plan_and_apply(api, store):
    await store.set("work_hours", "00:00-23:59")
    today = local_today(TZ)
    a = (
        await api.post("/api/tasks", json={"title": "Deep work", "due_date": today.isoformat(), "est_minutes": 15})
    ).json()

    plan = (await api.post("/api/plan")).json()
    if not plan["blocks"]:  # running in the last minutes of the day
        assert [t["id"] for t in plan["unplaced"]] == [a["id"]]
        return
    block = next(b for b in plan["blocks"] if b["task_id"] == a["id"])
    assert block["fixed"] is False

    applied = (
        await api.post(
            "/api/plan/apply", json={"date": today.isoformat(), "items": [{"task_id": a["id"], "time": block["start"]}]}
        )
    ).json()
    assert applied[0]["due_time"] == block["start"]


async def test_meta(api):
    meta = (await api.get("/api/meta")).json()
    assert meta["timezone"] == "Europe/Riga" and meta["ai"] is False and meta["calendar"] is False
    assert date.fromisoformat(meta["today"]) == local_today(TZ)
    assert meta["work_hours"] == ["09:00", "18:00"]

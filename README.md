# Personal Planner Bot

Single-user Telegram bot that captures tasks, plans the day and pings at the right time.
Stack: aiogram 3 · SQLAlchemy 2 (async) · Alembic · PostgreSQL (SQLite for local dev).

## Status

- [x] Phase 0 — skeleton, whitelist middleware, docker-compose, backups
- [x] Phase 1 — capture with regex parsing, `/today`, `/inbox`, `/add`, edit by reply
- [x] Phase 2 — scheduler, morning brief, reminders, evening review, /focus, rollover
- [ ] Phase 3 — LLM parsing, voice
- [ ] Phase 4 — calendar sync, recurring tasks
- [ ] Phase 5 — Mini App, weekly review

## Local run

```bash
cp .env .env          # set BOT_TOKEN (from @BotFather) and OWNER_ID (ask @userinfobot)
uv sync
uv run alembic upgrade head   # creates ./planner.db
uv run python -m bot
uv run pytest
```

## Deploy (VPS)

```bash
cp .env .env          # fill BOT_TOKEN, OWNER_ID, POSTGRES_PASSWORD
docker compose up -d --build  # runs migrations on start, long-polling
```

Nightly backup to R2: set `R2_BUCKET` / `R2_ENDPOINT` in `.env`, configure the `aws` CLI,
and add to crontab: `15 3 * * * cd /opt/planner && ./scripts/backup.sh >> backup.log 2>&1`.

## Usage

| Input | Result |
| --- | --- |
| `buy milk` | inbox |
| `call bank tomorrow !1` | tomorrow, high priority |
| `dentist fri 14:30` | next Friday, 14:30 |
| `pay rent 25.11` | 25 Nov (next year if already past) |
| reply to a task with `fri` / `new title` / `!1` | reschedules / renames / reprioritises |

**Daily loop:** morning brief (overdue + today + top 3 inbox) → Accept or Edit (tick tasks in/out;
unticked dated tasks move to tomorrow) → reminders for timed tasks (Done / +30 min / +2 h / Tomorrow)
→ evening review (Done / Tomorrow / Drop, then "x/y done") → at 00:01 open tasks roll over and count
as a slip. `/plan` and `/review` trigger either step by hand.

**Muting:** quiet hours (default 22:00–08:00) and `/focus 90` hold reminders back; they're delivered
when the mute ends. Change times with `/settings` and `/set`.

**Scheduling:** APScheduler runs in-process with an in-memory store. Durable state is in the DB — the
`reminders` table is polled every 30 s and `day_plans` records whether today's brief/review went out —
so jobs are rebuilt on start and anything missed while the bot was down is caught up.

Date and priority tokens are only read at the start or end of a message, so
"prepare monday slides" stays a plain title.

## Layout

```
bot/
  __main__.py       entrypoint (long polling)
  config.py         settings from .env
  parsing.py        regex task parser
  repo.py           task queries, reminders, rollover, day plans + events log
  planning.py       morning brief, plan accept, evening review, reminder delivery
  scheduler.py      APScheduler jobs + startup catch-up
  settings_store.py settings table, quiet hours / focus
  keyboards.py      inline keyboards & callback data
  formatting.py     message rendering
  middlewares/      owner whitelist, DB session per update
  handlers/         common, tasks (/today, /inbox, buttons), add (FSM), plan (/plan, /review, /focus, /set), capture
  db/               models, engine
migrations/         Alembic
scripts/backup.sh   pg_dump -> R2
```

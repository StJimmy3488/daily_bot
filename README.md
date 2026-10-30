# Personal Planner Bot

Single-user Telegram bot that captures tasks, plans the day and pings at the right time.
Stack: aiogram 3 · SQLAlchemy 2 (async) · Alembic · PostgreSQL (SQLite for local dev).

## Status

- [x] Phase 0 — skeleton, whitelist middleware, docker-compose, backups
- [x] Phase 1 — capture with regex parsing, `/today`, `/inbox`, `/add`, edit by reply
- [ ] Phase 2 — scheduler, morning brief, reminders, evening review
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

Date and priority tokens are only read at the start or end of a message, so
"prepare monday slides" stays a plain title.

## Layout

```
bot/
  __main__.py       entrypoint (long polling)
  config.py         settings from .env
  parsing.py        regex task parser
  repo.py           task queries + events log
  keyboards.py      inline keyboards & callback data
  formatting.py     message rendering
  middlewares/      owner whitelist, DB session per update
  handlers/         common, tasks (/today, /inbox, buttons), add (FSM), capture
  db/               models, engine
migrations/         Alembic
scripts/backup.sh   pg_dump -> R2
```

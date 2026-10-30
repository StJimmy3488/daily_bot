# Personal Planner Bot

Single-user Telegram bot that captures tasks, plans the day and pings at the right time.
Stack: aiogram 3 · SQLAlchemy 2 (async) · Alembic · PostgreSQL (SQLite for local dev).

## Status

- [x] Phase 0 — skeleton, whitelist middleware, docker-compose, backups
- [x] Phase 1 — capture with regex parsing, `/today`, `/inbox`, `/add`, edit by reply
- [x] Phase 2 — scheduler, morning brief, reminders, evening review, /focus, rollover
- [x] Phase 3 — Claude parsing, local voice transcription, natural edits and questions
- [x] Phase 4 — Google Calendar sync and write-back, meeting heads-ups, smart plan, recurring tasks
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

**Natural language and voice (Phase 3).** With `ANTHROPIC_API_KEY` set, every text and voice note
goes to Claude (`AI_MODEL`, default Haiku 5.5): *"remind me to call mom tomorrow at 7, buy milk, and
the dentist moved to Friday"*. Voice notes are transcribed locally with faster-whisper
(`WHISPER_MODEL`, default `small`; downloaded once into the `whisper-models` volume).

- A single new task is saved immediately; a reply to a task card that changes only that task is
  applied immediately.
- Anything else (several tasks, edits, done/drop) shows a preview — tick items in or out, then Save.
- Questions ("what's left this week?") get a short answer.
- Only task titles, dates, times and priorities are sent to Claude. Every call is logged with its
  cost in `ai_calls`; `/ai` shows the monthly total.
- No key, an API error or a refusal falls back to the regex parser below.

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

**Calendar (Phase 4):** all calendars that are shown in Google Calendar are mirrored every 15 min
(yesterday to +14 days, declined and cancelled events skipped). The morning brief lists meetings
first, you get a ping 10 min before each meeting with its link (quiet hours apply, focus doesn't),
and "block 2h for the audit tomorrow" creates an event in your primary calendar after you confirm.

**Smart plan:** `/smartplan`, the brief's 🧠 button or "plan my day". Claude (`AI_PLAN_MODEL`) orders
today's tasks and estimates durations; a deterministic fitter then places them into free time inside
work hours (`/set work 09:00-18:00`), so nothing lands on a meeting — events marked *free* don't
block. Saving the plan sets each task's time, which schedules a reminder at the slot start.

**Recurring tasks:** "pay rent on the 1st of every month", "water plants every day". Stored as an
RRULE; finishing or dropping one occurrence creates the next.

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
  assistant.py      Claude: prompt, strict tools, validation, cost
  actions.py        describe / apply proposed task actions
  transcribe.py     local faster-whisper speech-to-text
  google_calendar.py  Google OAuth + Calendar REST client (aiohttp)
  calendar_sync.py  mirror events into calendar_events
  smart_plan.py     fit tasks into free time around meetings
  recurrence.py     RRULE helpers
  web.py            FastAPI app (health, OAuth callback) served by uvicorn in-process
  planning.py       morning brief, plan accept, evening review, reminder delivery
  scheduler.py      APScheduler jobs + startup catch-up
  settings_store.py settings table, quiet hours / focus
  keyboards.py      inline keyboards & callback data
  formatting.py     message rendering
  middlewares/      owner whitelist, DB session per update
  handlers/         common, tasks (/today, /inbox, buttons), add (FSM), plan (/plan, /review, /focus, /set),
                    calendar (/calendar, /smartplan), capture (text, voice, replies, AI previews)
  db/               models, engine
migrations/         Alembic
scripts/backup.sh   pg_dump -> R2
```

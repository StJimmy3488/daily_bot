"""HTTP side of the bot: health check and the Google OAuth callback (Mini App comes in phase 5)."""

import contextlib
import logging
import secrets
from datetime import datetime, timedelta
from html import escape

import uvicorn
from aiogram import Bot
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.clock import utcnow
from bot.google_calendar import CALLBACK_PATH, CalendarError, GoogleCalendar
from bot.settings_store import SettingsStore

log = logging.getLogger(__name__)

STATE_TTL = timedelta(minutes=15)


async def new_oauth_state(store: SettingsStore) -> str:
    state = secrets.token_urlsafe(24)
    await store.set("google_oauth_state", f"{state}|{(utcnow() + STATE_TTL).isoformat()}")
    return state


async def check_oauth_state(store: SettingsStore, state: str) -> bool:
    saved = await store.get("google_oauth_state")
    if "|" not in saved:
        return False
    expected, expires = saved.split("|", 1)
    return secrets.compare_digest(state, expected) and utcnow() < datetime.fromisoformat(expires)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:28rem;margin:4rem auto;padding:0 1rem;text-align:center}}</style>
</head><body><h2>{escape(title)}</h2><p>{escape(body)}</p></body></html>"""
    return HTMLResponse(html, status_code=status)


def create_app(
    bot: Bot, sessionmaker: async_sessionmaker, chat_id: int, gcal: GoogleCalendar | None, on_connected
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get(CALLBACK_PATH)
    async def google_callback(code: str = "", state: str = "", error: str = "") -> HTMLResponse:
        if gcal is None:
            return _page("Not configured", "Google Calendar isn't set up on this bot.", 404)
        if error:
            return _page("Not connected", f"Google said: {error}. You can try again with /calendar.", 400)

        async with sessionmaker() as session, session.begin():
            store = SettingsStore(session)
            if not code or not await check_oauth_state(store, state):
                return _page("Link expired", "Send /calendar in Telegram to get a fresh link.", 400)
            try:
                tokens = await gcal.exchange_code(code)
            except CalendarError:
                log.exception("OAuth code exchange failed")
                return _page("Something went wrong", "Couldn't finish connecting. Try /calendar again.", 502)
            refresh_token = tokens.get("refresh_token")
            if not refresh_token:
                return _page("No offline access", "Google didn't grant offline access. Try /calendar again.", 400)
            await store.set("google_refresh_token", refresh_token)
            await store.set("google_oauth_state", "")

        await bot.send_message(chat_id, "📅 Google Calendar connected. Syncing your events…")
        await on_connected()
        return _page("Connected ✅", "Google Calendar is linked. You can close this tab.")

    return app


class WebServer(uvicorn.Server):
    """uvicorn inside the bot's event loop; aiogram owns the process signals."""

    def capture_signals(self):
        return contextlib.nullcontext()

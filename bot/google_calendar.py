"""Minimal async Google Calendar client: OAuth (web flow), list calendars/events, insert events."""

import logging
import time as monotonic_time
from datetime import datetime
from urllib.parse import urlencode

import aiohttp

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
# Read all calendars; write events only (for confirmed write-back).
SCOPES = "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events"
CALLBACK_PATH = "/oauth/google/callback"


class CalendarAuthError(Exception):
    """The refresh token was revoked or expired; the user has to reconnect."""


class CalendarError(Exception):
    pass


class GoogleCalendar:
    def __init__(self, client_id: str, client_secret: str, public_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = public_url.rstrip("/") + CALLBACK_PATH
        self._access: tuple[str, str, float] | None = None  # (refresh token, access token, expires at)
        self._timeout = aiohttp.ClientTimeout(total=20)

    def auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",  # always return a refresh token
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _token_request(self, data: dict) -> dict:
        data = {"client_id": self.client_id, "client_secret": self.client_secret, **data}
        async with aiohttp.ClientSession(timeout=self._timeout) as http, http.post(TOKEN_URL, data=data) as resp:
            body = await resp.json(content_type=None)
            if resp.status == 400 and body.get("error") == "invalid_grant":
                raise CalendarAuthError(body.get("error_description", "invalid_grant"))
            if resp.status != 200:
                raise CalendarError(f"token endpoint {resp.status}: {body}")
            return body

    async def exchange_code(self, code: str) -> dict:
        return await self._token_request(
            {"code": code, "grant_type": "authorization_code", "redirect_uri": self.redirect_uri}
        )

    async def revoke(self, refresh_token: str) -> None:
        async with aiohttp.ClientSession(timeout=self._timeout) as http:
            await http.post(REVOKE_URL, data={"token": refresh_token})
        self._access = None

    async def _access_token(self, refresh_token: str) -> str:
        if self._access and self._access[0] == refresh_token and self._access[2] > monotonic_time.monotonic() + 60:
            return self._access[1]
        body = await self._token_request({"refresh_token": refresh_token, "grant_type": "refresh_token"})
        self._access = (refresh_token, body["access_token"], monotonic_time.monotonic() + body.get("expires_in", 3600))
        return self._access[1]

    async def _request(self, refresh_token: str, method: str, path: str, **kwargs) -> dict:
        token = await self._access_token(refresh_token)
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(timeout=self._timeout) as http:
            async with http.request(method, API + path, headers=headers, **kwargs) as resp:
                body = await resp.json(content_type=None)
                if resp.status == 401:
                    self._access = None
                    raise CalendarAuthError("unauthorized")
                if resp.status >= 400:
                    raise CalendarError(f"{method} {path} -> {resp.status}: {body}")
                return body

    async def list_calendars(self, refresh_token: str) -> list[dict]:
        body = await self._request(refresh_token, "GET", "/users/me/calendarList")
        return body.get("items", [])

    async def list_events(self, refresh_token: str, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
        items, page_token = [], None
        while True:
            params = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",  # expand recurring events into instances
                "orderBy": "startTime",
                "maxResults": "250",
            }
            if page_token:
                params["pageToken"] = page_token
            body = await self._request(refresh_token, "GET", f"/calendars/{calendar_id}/events", params=params)
            items += body.get("items", [])
            page_token = body.get("nextPageToken")
            if not page_token:
                return items

    async def insert_event(self, refresh_token: str, title: str, start: datetime, end: datetime, tz: str) -> dict:
        payload = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": tz},
            "end": {"dateTime": end.isoformat(), "timeZone": tz},
        }
        return await self._request(refresh_token, "POST", "/calendars/primary/events", json=payload)

"""Regex-based task parser: `buy milk tomorrow 18:00 !1` -> structured fields.

Date/priority/time tokens are only recognised at the start or end of the
message, so a title like "prepare monday slides" stays intact.
"""

import re
from dataclasses import dataclass
from datetime import date, time, timedelta

RELATIVE_DAYS = {
    "today": 0,
    "tod": 0,
    "сегодня": 0,
    "tomorrow": 1,
    "tmr": 1,
    "tmrw": 1,
    "завтра": 1,
    "послезавтра": 2,
}

WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "пн": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "вт": 1,
    "wed": 2,
    "wednesday": 2,
    "ср": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "чт": 3,
    "fri": 4,
    "friday": 4,
    "пт": 4,
    "sat": 5,
    "saturday": 5,
    "сб": 5,
    "sun": 6,
    "sunday": 6,
    "вс": 6,
}

# Dangling words left behind after stripping a trailing date: "call bank on fri"
CONNECTORS = {"on", "by", "at", "for", "until", "due", "в", "на", "до", "к"}

PRIORITY_RE = re.compile(r"^!([1-3])$")
DATE_RE = re.compile(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}|\d{2}))?$")
TIME_RE = re.compile(r"^@?([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class ParsedTask:
    title: str
    priority: int | None = None
    due_date: date | None = None
    due_time: time | None = None


def parse_date(token: str, today: date) -> date | None:
    token = token.lower()
    if token in RELATIVE_DAYS:
        return today + timedelta(days=RELATIVE_DAYS[token])
    if token in WEEKDAYS:
        # Always the *next* such weekday: "fri" typed on a Friday means next week.
        ahead = (WEEKDAYS[token] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    if m := DATE_RE.match(token):
        day, month, year = int(m[1]), int(m[2]), m[3]
        y = (int(year) + 2000 if len(year) == 2 else int(year)) if year else today.year
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if not year and d < today:
            d = d.replace(year=y + 1)
        return d
    return None


def _apply(token: str, result: ParsedTask, today: date) -> bool:
    """Try to consume a token into `result`. Each field is filled at most once."""
    clean = token.rstrip(",;").lower()
    if result.priority is None and (m := PRIORITY_RE.match(clean)):
        result.priority = int(m[1])
        return True
    if result.due_time is None and (m := TIME_RE.match(clean)):
        result.due_time = time(int(m[1]), int(m[2]))
        return True
    if result.due_date is None and (d := parse_date(clean, today)):
        result.due_date = d
        return True
    return False


def parse_task(text: str, today: date) -> ParsedTask:
    tokens = text.split()
    result = ParsedTask(title="")

    start = 0
    while start < len(tokens) and _apply(tokens[start], result, today):
        start += 1

    end = len(tokens)
    while end > start and _apply(tokens[end - 1], result, today):
        end -= 1
    if end < len(tokens):
        while end > start and tokens[end - 1].lower() in CONNECTORS:
            end -= 1

    result.title = " ".join(tokens[start:end]).strip(" ,;-")
    return result

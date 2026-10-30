"""Recurring tasks as RFC 5545 RRULE strings (python-dateutil)."""

from datetime import date, datetime, time

from dateutil.rrule import rrulestr

_FREQ_NAMES = {"DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly", "YEARLY": "yearly"}


def normalize_rule(rule: str) -> str:
    """Validate and canonicalise a rule. Raises ValueError if it's not a usable RRULE."""
    rule = rule.strip().upper().removeprefix("RRULE:")
    if "FREQ=" not in rule or "DTSTART" in rule:
        raise ValueError(f"not an RRULE: {rule!r}")
    try:
        rrulestr(rule, dtstart=datetime(2000, 1, 1))
    except (ValueError, TypeError) as e:
        raise ValueError(f"invalid RRULE {rule!r}: {e}") from e
    return rule


def next_occurrence(rule: str, due: date, today: date) -> date | None:
    """The next date strictly after both the current due date and today.

    Finishing a weekly Monday task on Wednesday schedules next Monday, and
    finishing it early doesn't schedule a second one this week.
    """
    after = datetime.combine(max(due, today), time())
    nxt = rrulestr(rule, dtstart=datetime.combine(due, time())).after(after, inc=False)
    return nxt.date() if nxt else None


def describe_rule(rule: str) -> str:
    parts = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    text = _FREQ_NAMES.get(parts.get("FREQ", ""), "repeats")
    if parts.get("INTERVAL", "1") != "1":
        text = f"every {parts['INTERVAL']} × {text}"
    if "BYDAY" in parts:
        text += f" on {parts['BYDAY'].lower()}"
    if "BYMONTHDAY" in parts:
        text += f" on day {parts['BYMONTHDAY']}"
    return text


def first_occurrence(rule: str, today: date) -> date | None:
    """First date on or after today, for a repeating task created without a date."""
    nxt = rrulestr(rule, dtstart=datetime.combine(today, time())).after(datetime.combine(today, time()), inc=True)
    return nxt.date() if nxt else None

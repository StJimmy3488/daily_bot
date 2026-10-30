from datetime import date, time

import pytest

from bot.parsing import parse_task

# Thursday
TODAY = date(2026, 10, 29)


@pytest.mark.parametrize(
    ("text", "title", "priority", "due_date", "due_time"),
    [
        ("buy milk", "buy milk", None, None, None),
        ("call bank tomorrow !1", "call bank", 1, date(2026, 10, 30), None),
        ("!3 tmr water plants", "water plants", 3, date(2026, 10, 30), None),
        ("dentist fri 14:30", "dentist", None, date(2026, 10, 30), time(14, 30)),
        ("pay rent 25.11", "pay rent", None, date(2026, 11, 25), None),
        ("renew passport 05.03", "renew passport", None, date(2027, 3, 5), None),
        ("tax return 1.4.2027", "tax return", None, date(2027, 4, 1), None),
        ("send report on mon", "send report", None, date(2026, 11, 2), None),
        ("standup thu", "standup", None, date(2026, 11, 5), None),  # same weekday -> next week
        ("prepare monday slides", "prepare monday slides", None, None, None),
        ("позвонить маме завтра", "позвонить маме", None, date(2026, 10, 30), None),
        ("gym 18:00", "gym", None, None, time(18, 0)),
        ("tomorrow", "", None, date(2026, 10, 30), None),
        ("meeting 31.02", "meeting 31.02", None, None, None),  # invalid date stays in title
    ],
)
def test_parse_task(text, title, priority, due_date, due_time):
    parsed = parse_task(text, TODAY)
    assert parsed.title == title
    assert parsed.priority == priority
    assert parsed.due_date == due_date
    assert parsed.due_time == due_time

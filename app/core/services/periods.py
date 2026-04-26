"""Period-chip helpers. Map a chip key to a (date_from, date_to) tuple.

Used by the transactions list page. Keeping the math here means the view stays thin
and the behavior is unit-testable without a request.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

PERIOD_KEYS = ("week", "30d", "this_month", "last_month", "6m", "12m", "custom")

PERIOD_LABELS = {
    "week": "This Week",
    "30d": "Last 30 Days",
    "this_month": "This Month",
    "last_month": "Last Month",
    "6m": "6M",
    "12m": "12M",
    "custom": "Custom",
}


def _months_ago(today: date, months: int) -> date:
    year, month = today.year, today.month - months
    while month < 1:
        month += 12
        year -= 1
    day = min(today.day, monthrange(year, month)[1])
    return date(year, month, day)


def period_range(period: str, today: date | None = None) -> tuple[date | None, date | None]:
    """Return (start, end) inclusive. `custom` returns (None, None); caller parses explicit dates."""
    today = today or date.today()
    if period == "week":
        return (today - timedelta(days=today.weekday()), today)
    if period == "30d":
        return (today - timedelta(days=29), today)
    if period == "this_month":
        return (today.replace(day=1), today)
    if period == "last_month":
        first_of_this = today.replace(day=1)
        end_of_last = first_of_this - timedelta(days=1)
        return (end_of_last.replace(day=1), end_of_last)
    if period == "6m":
        return (_months_ago(today, 6), today)
    if period == "12m":
        return (_months_ago(today, 12), today)
    return (None, None)

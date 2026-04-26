from datetime import date, timedelta

import pytest

from core.services.periods import period_range


def test_week_starts_on_monday():
    wed = date(2026, 4, 15)  # Wednesday
    start, end = period_range("week", today=wed)
    assert start == date(2026, 4, 13)  # Monday
    assert end == wed


def test_30d_inclusive():
    today = date(2026, 4, 30)
    start, end = period_range("30d", today=today)
    assert end == today
    assert (end - start).days == 29


def test_this_month_first_to_today():
    today = date(2026, 4, 18)
    start, end = period_range("this_month", today=today)
    assert start == date(2026, 4, 1)
    assert end == today


def test_last_month_full_range():
    today = date(2026, 4, 18)
    start, end = period_range("last_month", today=today)
    assert start == date(2026, 3, 1)
    assert end == date(2026, 3, 31)


def test_6m_six_months_back():
    today = date(2026, 4, 18)
    start, end = period_range("6m", today=today)
    assert start == date(2025, 10, 18)
    assert end == today


def test_6m_handles_month_length_mismatch():
    # Aug 31 minus 6 months would be Feb 31 (invalid); fall back to Feb 28 (non-leap).
    today = date(2025, 8, 31)
    start, _ = period_range("6m", today=today)
    assert start == date(2025, 2, 28)


def test_12m_one_year_back():
    today = date(2026, 4, 18)
    start, _ = period_range("12m", today=today)
    assert start == date(2025, 4, 18)


def test_custom_returns_none_pair():
    assert period_range("custom") == (None, None)


def test_unknown_returns_none_pair():
    assert period_range("bogus") == (None, None)


def test_default_today_is_safe():
    start, end = period_range("30d")
    assert end - start == timedelta(days=29)


@pytest.mark.parametrize("key", ["week", "30d", "this_month", "last_month", "6m", "12m"])
def test_every_key_returns_real_range(key):
    start, end = period_range(key)
    assert start is not None and end is not None
    assert start <= end

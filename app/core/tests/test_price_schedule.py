"""Tests for the price-refresh CLI command + django-q schedule setup."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django_q.models import Schedule


@pytest.mark.django_db
def test_setup_schedules_creates_daily_refresh_prices():
    out = StringIO()
    call_command("setup_schedules", stdout=out)
    text = out.getvalue()
    assert "refresh_prices" in text
    assert "created" in text

    sched = Schedule.objects.get(name="refresh_prices")
    assert sched.cron == "15 16 * * *"
    assert sched.schedule_type == Schedule.CRON
    assert sched.repeats == -1
    assert sched.args == "'refresh_prices'"


@pytest.mark.django_db
def test_setup_schedules_is_idempotent():
    call_command("setup_schedules", stdout=StringIO())
    call_command("setup_schedules", stdout=StringIO())
    assert Schedule.objects.filter(name="refresh_prices").count() == 1


@pytest.mark.django_db
def test_refresh_prices_command_noop_without_profiles():
    """With no default profile, the command must still exit cleanly."""
    out = StringIO()
    call_command("refresh_prices", stdout=out)
    text = out.getvalue()
    assert "profiles=0" in text
    assert "ticks_written=0" in text

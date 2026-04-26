"""``python manage.py setup_schedules`` -- idempotently install django-q2 schedules.

Ensures the following ``django_q.models.Schedule`` rows exist::

    auto_snapshot   -- daily rollup snapshot (already shipped pre-Phase E)
    refresh_prices  -- 16:15 Asia/Kolkata daily price refresh (Phase E2)

Safe to run repeatedly; each call is a ``get_or_create`` against
``Schedule.name``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

REFRESH_PRICES_NAME = "refresh_prices"
REFRESH_PRICES_FUNC = (
    "django.core.management.call_command"  # runs our management command
)
REFRESH_PRICES_CRON = "15 16 * * *"  # 16:15 local (Asia/Kolkata by settings)


class Command(BaseCommand):
    help = "Idempotently create django-q2 schedules for recurring jobs."

    def handle(self, *args, **options):
        _, created = Schedule.objects.get_or_create(
            name=REFRESH_PRICES_NAME,
            defaults={
                "func": REFRESH_PRICES_FUNC,
                "args": "'refresh_prices'",
                "schedule_type": Schedule.CRON,
                "cron": REFRESH_PRICES_CRON,
                "repeats": -1,
                "next_run": timezone.now(),
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{REFRESH_PRICES_NAME}: {'created' if created else 'already registered'} "
                f"(cron={REFRESH_PRICES_CRON} tz={timezone.get_current_timezone_name()})"
            )
        )

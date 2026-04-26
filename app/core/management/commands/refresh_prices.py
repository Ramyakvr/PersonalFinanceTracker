"""``python manage.py refresh_prices`` -- run a price refresh for every opted-in profile.

Callable from the CLI (for one-off backfills) and from ``django-q2`` (scheduled
daily at 16:15 Asia/Kolkata). The underlying service respects the
``UserPreferences.live_price_enabled`` toggle, so this command is safe to
run unconditionally -- it quietly no-ops for any profile that hasn't opted in.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services.prices import refresh_prices_all


class Command(BaseCommand):
    help = "Refresh NSE / AMFI prices for every opted-in profile (idempotent)."

    def handle(self, *args, **options):
        summary = refresh_prices_all()
        self.stdout.write(
            self.style.SUCCESS(
                
                    f"refresh_prices: profiles={summary['profiles']} "
                    f"ticks_written={summary['ticks_written']}"
                
            )
        )
        for err in summary["errors"][:5]:
            self.stdout.write(self.style.WARNING(f"  ! {err}"))

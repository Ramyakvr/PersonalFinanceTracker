"""Take one auto-snapshot per default profile.

Meant to run nightly via `django-q2` or `launchd`. Idempotent within
`core.services.snapshots.AUTO_MIN_GAP_HOURS`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services.snapshots import auto_snapshot_all


class Command(BaseCommand):
    help = "Take an automatic snapshot for every default profile (idempotent)."

    def handle(self, *args, **options):
        result = auto_snapshot_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"Auto-snapshot: created={result['created']} skipped={result['skipped']}"
            )
        )

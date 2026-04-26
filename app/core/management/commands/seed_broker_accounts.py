"""Seed BrokerAccount rows for the user's known broker client IDs.

Idempotent: safe to re-run. Pre-creates one BrokerAccount per entry in
``KNOWN_CLIENT_IDS`` so the investments dashboard can list them before any
file has been imported. Existing rows are left untouched.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.models import BrokerAccount, Profile
from core.services.imports.brokers import KNOWN_CLIENT_IDS


class Command(BaseCommand):
    help = "Pre-create BrokerAccount rows for known client IDs."

    def handle(self, *args, **kwargs):
        profile = Profile.objects.filter(is_default=True).first()
        if profile is None:
            self.stderr.write("No default profile. Run `manage.py seed` first.")
            return
        created = 0
        for broker_key, client_id in KNOWN_CLIENT_IDS:
            ba, was_created = BrokerAccount.objects.get_or_create(
                profile=profile,
                broker_key=broker_key,
                account_label=client_id,
                defaults={"client_code": client_id},
            )
            if was_created:
                created += 1
                self.stdout.write(f"  + {broker_key}/{client_id}")
            elif not ba.client_code:
                ba.client_code = client_id
                ba.save(update_fields=["client_code"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} new broker account(s); {len(KNOWN_CLIENT_IDS) - created} already existed."
            )
        )

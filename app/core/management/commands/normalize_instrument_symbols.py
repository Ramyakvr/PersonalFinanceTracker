"""Scrub non-ticker values out of ``Instrument.exchange_symbol``.

Older versions of the Chola adapter wrote the company name into
``symbol`` for dividends and corporate actions; the importer then planted
that name into ``exchange_symbol``, which broke NSE bhavcopy lookups
(the bhavcopy is keyed on the short ticker like ``TATASTEEL``).

This command finds rows whose ``exchange_symbol`` clearly isn't an NSE
ticker (contains whitespace, mixed case, or company-suffix tokens) and
clears the field so a future tradebook import can repopulate it with the
real ticker. Use ``--dry-run`` first to preview.
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from core.models import Instrument

# NSE tickers are uppercase letters/digits, 1-15 chars, sometimes with a
# trailing ``-`` segment (e.g. TATAMTRDVR, IDEA, INFOSYSBE). Anything with
# a space, lowercase letters, or a dot is almost certainly a name fragment.
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-&]{0,14}$")
_NAME_HINTS = ("Ltd", "Limited", "Pvt", "Inc", "Co.", "Industries", "Bank")


def _looks_like_name(symbol: str) -> bool:
    if not symbol:
        return False
    if _TICKER_RE.match(symbol):
        return False
    if any(ch.isspace() for ch in symbol):
        return True
    if any(ch.islower() for ch in symbol):
        return True
    return any(hint in symbol for hint in _NAME_HINTS)


class Command(BaseCommand):
    help = "Clear non-ticker values from Instrument.exchange_symbol."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        bad = []
        for inst in Instrument.objects.filter(kind="STOCK").order_by("id"):
            if _looks_like_name(inst.exchange_symbol):
                bad.append(inst)
        self.stdout.write(f"Found {len(bad)} instrument(s) with non-ticker exchange_symbol")
        for inst in bad:
            self.stdout.write(
                f"  id={inst.id} isin={inst.isin!r} sym={inst.exchange_symbol!r} "
                f"name={inst.name!r}"
            )
        if dry_run or not bad:
            if dry_run:
                self.stdout.write(self.style.WARNING("Dry run -- no changes written"))
            return
        for inst in bad:
            inst.exchange_symbol = ""
            inst.save(update_fields=["exchange_symbol"])
        self.stdout.write(self.style.SUCCESS(f"Cleared exchange_symbol on {len(bad)} row(s)"))

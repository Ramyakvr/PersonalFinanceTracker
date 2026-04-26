"""``python manage.py inspect_prices``

Diagnose why ``refresh_prices`` did not fetch a tick for an Instrument.
For each STOCK row in the default profile, prints one line with the
current ``exchange_symbol``, the ISIN, whether the NSE master resolves
the ISIN to a ticker, whether today's bhavcopy has that ticker, and
whether a ``PriceTick`` already exists.

Read-only: never writes to the DB. Use this to pinpoint the gap before
deciding whether to (a) hand-edit ``Instrument.exchange_symbol`` in
admin, (b) re-import a broker file that carries the ticker, or (c)
extend ``KNOWN_CLIENT_IDS`` / accepted bhavcopy SERIES.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from core.models import Instrument, InstrumentKind, PriceTick, Profile
from core.services.prices_fetchers.nse import _default_loader, parse_bhavcopy
from core.services.prices_fetchers.nse_master import fetch_isin_to_symbol

MAX_FALLBACK_DAYS = 5


def _today_bhavcopy() -> tuple[dict[str, tuple], date | None]:
    cur = date.today()
    for _ in range(MAX_FALLBACK_DAYS + 1):
        if cur.weekday() < 5:
            blob = _default_loader(cur)
            if blob:
                parsed = parse_bhavcopy(blob)
                if parsed:
                    return parsed, cur
        cur -= timedelta(days=1)
    return {}, None


class Command(BaseCommand):
    help = "Diagnose missing live prices for STOCK Instruments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Print only instruments without a recent PriceTick.",
        )

    def handle(self, *args, only_missing: bool = False, **opts):
        profile = Profile.objects.filter(is_default=True).first()
        if profile is None:
            self.stderr.write("No default profile.")
            return

        self.stdout.write("Fetching NSE master ...")
        master = fetch_isin_to_symbol()
        self.stdout.write(f"  {len(master)} ISIN -> SYMBOL entries")

        self.stdout.write("Fetching today's bhavcopy ...")
        bhavcopy, bhav_date = _today_bhavcopy()
        if bhav_date:
            self.stdout.write(f"  {len(bhavcopy)} symbols from {bhav_date}")
        else:
            self.stdout.write(self.style.WARNING("  no bhavcopy in last 6 business days"))

        rows = []
        for inst in (
            Instrument.objects.filter(profile=profile, kind=InstrumentKind.STOCK).order_by("name")
        ):
            tick = (
                PriceTick.objects.filter(instrument=inst).order_by("-as_of").first()
            )
            master_sym = master.get((inst.isin or "").upper())
            in_bhavcopy = (
                inst.exchange_symbol.upper() in bhavcopy
                if inst.exchange_symbol
                else False
            )
            if only_missing and tick is not None:
                continue
            rows.append(
                {
                    "name": inst.name,
                    "isin": inst.isin or "—",
                    "symbol": inst.exchange_symbol or "—",
                    "master": master_sym or "—",
                    "in_bhav": "yes" if in_bhavcopy else "no",
                    "last_tick": (
                        f"{tick.as_of} {tick.price}" if tick else "—"
                    ),
                }
            )

        if not rows:
            self.stdout.write(self.style.SUCCESS("No matching instruments."))
            return

        # Pretty-print as fixed-width columns for terminal readability.
        widths = {k: max(len(k), max(len(str(r[k])) for r in rows)) for k in rows[0]}
        header = "  ".join(k.ljust(widths[k]) for k in rows[0])
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(header))
        for r in rows:
            self.stdout.write("  ".join(str(r[k]).ljust(widths[k]) for k in r))

        # Summary buckets to highlight the most common failure mode.
        no_isin = sum(1 for r in rows if r["isin"] == "—")
        unresolved = sum(1 for r in rows if r["isin"] != "—" and r["master"] == "—")
        missing_in_bhav = sum(
            1 for r in rows if r["symbol"] != "—" and r["in_bhav"] == "no"
        )
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary"))
        self.stdout.write(f"  total inspected:           {len(rows)}")
        self.stdout.write(f"  no ISIN on instrument:     {no_isin}")
        self.stdout.write(f"  ISIN not in NSE master:    {unresolved}")
        self.stdout.write(f"  symbol set but absent from bhavcopy: {missing_in_bhav}")

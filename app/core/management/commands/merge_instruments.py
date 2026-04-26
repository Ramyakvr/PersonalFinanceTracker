"""Merge duplicate ``Instrument`` rows.

Caused by ISIN drift after corporate actions (face-value change, demerger)
or by tradebooks that reach the importer before dividend statements when the
two sources spell ISIN differently. This command rewires every FK from the
loser instruments to a single winner and deletes the losers.

Usage::

    python manage.py merge_instruments --winner 19 --losers 109
    python manage.py merge_instruments --winner 19 --losers 109 --symbol ITC --dry-run

The winner inherits each loser's ISIN as an alias (``Instrument.isin_aliases``)
so future imports keyed on the legacy ISIN still resolve to the merged row.
``--symbol`` lets you fix a bad ``exchange_symbol`` on the winner in the same
transaction.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    Asset,
    CorporateAction,
    DividendRecord,
    Instrument,
    PriceTick,
    StockTrade,
)


def _split_ids(raw: str) -> list[int]:
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as exc:
            raise CommandError(f"Bad id {part!r}: not an integer") from exc
    return out


class Command(BaseCommand):
    help = "Merge duplicate Instrument rows into a chosen winner."

    def add_arguments(self, parser):
        parser.add_argument("--winner", type=int, required=True, help="Instrument id to keep")
        parser.add_argument(
            "--losers",
            type=str,
            required=True,
            help="Comma-separated Instrument ids to merge into the winner",
        )
        parser.add_argument(
            "--symbol",
            type=str,
            default=None,
            help="Optional: overwrite the winner's exchange_symbol after merging",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Optional: overwrite the winner's name after merging",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change but make no DB writes",
        )

    def handle(self, *args, **opts):
        winner_id: int = opts["winner"]
        loser_ids = _split_ids(opts["losers"])
        new_symbol: str | None = opts["symbol"]
        new_name: str | None = opts["name"]
        dry_run: bool = opts["dry_run"]

        if winner_id in loser_ids:
            raise CommandError("Winner cannot also be a loser")

        winner = Instrument.objects.filter(id=winner_id).first()
        if winner is None:
            raise CommandError(f"Winner id={winner_id} not found")
        losers = list(Instrument.objects.filter(id__in=loser_ids))
        missing = set(loser_ids) - {l.id for l in losers}
        if missing:
            raise CommandError(f"Loser ids not found: {sorted(missing)}")

        # Cross-profile guard: ISINs are namespaced per profile so refusing
        # to merge across profiles avoids leaking trades between users.
        for loser in losers:
            if loser.profile_id != winner.profile_id:
                raise CommandError(
                    f"Loser id={loser.id} belongs to profile {loser.profile_id}; "
                    f"winner is in profile {winner.profile_id}"
                )
            if loser.kind != winner.kind:
                raise CommandError(
                    f"Loser id={loser.id} kind={loser.kind} != winner kind={winner.kind}"
                )

        self.stdout.write(
            f"Winner: id={winner.id} isin={winner.isin!r} sym={winner.exchange_symbol!r} "
            f"name={winner.name!r}"
        )
        for loser in losers:
            self.stdout.write(
                f"Loser:  id={loser.id} isin={loser.isin!r} sym={loser.exchange_symbol!r} "
                f"name={loser.name!r}"
            )

        plan = self._count_plan(winner, losers)
        self.stdout.write("Plan:")
        for line in plan:
            self.stdout.write(f"  {line}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run -- no changes written"))
            return

        with transaction.atomic():
            self._reassign(winner, losers)
            self._merge_aliases(winner, losers)
            if new_symbol is not None:
                winner.exchange_symbol = new_symbol
            if new_name is not None:
                winner.name = new_name
            winner.save()
            for loser in losers:
                loser.delete()

        self.stdout.write(self.style.SUCCESS(f"Merged {len(losers)} loser(s) into id={winner.id}"))

    # ------------------------------------------------------------------

    def _count_plan(self, winner: Instrument, losers: list[Instrument]) -> list[str]:
        lines = []
        for loser in losers:
            counts = {
                "trades": StockTrade.objects.filter(instrument=loser).count(),
                "dividends": DividendRecord.objects.filter(instrument=loser).count(),
                "corp_actions": CorporateAction.objects.filter(instrument=loser).count(),
                "corp_actions_as_new": CorporateAction.objects.filter(new_instrument=loser).count(),
                "assets": Asset.objects.filter(instrument=loser).count(),
                "price_ticks": PriceTick.objects.filter(instrument=loser).count(),
            }
            joined = ", ".join(f"{k}={v}" for k, v in counts.items() if v)
            lines.append(f"id={loser.id}: reassign {joined or '(no rows)'} -> id={winner.id}")
        return lines

    def _reassign(self, winner: Instrument, losers: list[Instrument]) -> None:
        ids = [l.id for l in losers]
        StockTrade.objects.filter(instrument_id__in=ids).update(instrument=winner)
        DividendRecord.objects.filter(instrument_id__in=ids).update(instrument=winner)
        CorporateAction.objects.filter(instrument_id__in=ids).update(instrument=winner)
        CorporateAction.objects.filter(new_instrument_id__in=ids).update(new_instrument=winner)
        Asset.objects.filter(instrument_id__in=ids).update(instrument=winner)
        # PriceTick has unique (instrument, source, as_of); collisions on merge
        # are silently dropped in favour of the winner's tick.
        for loser in losers:
            for tick in PriceTick.objects.filter(instrument=loser):
                exists = PriceTick.objects.filter(
                    instrument=winner, source=tick.source, as_of=tick.as_of
                ).exists()
                if exists:
                    tick.delete()
                else:
                    tick.instrument = winner
                    tick.save(update_fields=["instrument"])

    def _merge_aliases(self, winner: Instrument, losers: list[Instrument]) -> None:
        aliases: list[str] = list(winner.isin_aliases or [])
        seen = {winner.isin, *aliases}
        for loser in losers:
            if loser.isin and loser.isin not in seen:
                aliases.append(loser.isin)
                seen.add(loser.isin)
            for a in loser.isin_aliases or []:
                if a and a not in seen:
                    aliases.append(a)
                    seen.add(a)
        winner.isin_aliases = aliases

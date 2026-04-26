"""Backfill ``Asset.instrument`` for equity / MF assets created before Phase A.

For every Asset whose ``subtype`` maps to a tradeable instrument kind:

1. If the asset already has an ``instrument`` FK set, skip it.
2. Look for an existing Instrument in the same profile by ``exchange_symbol``
   (the old ``instrument_symbol`` column) when present and non-blank.
3. Otherwise create a placeholder Instrument with ``needs_review=True`` so
   the UI can surface "please confirm ISIN" later.

Reverse: unlink (set ``Asset.instrument = None``). We never drop the
Instrument rows because they may already be referenced by StockTrade /
DividendRecord rows created after this migration.
"""

from __future__ import annotations

from django.db import migrations

STOCK_SUBTYPES = {"DIRECT_STOCK", "EMPLOYER_STOCK", "ETF", "GOLD_ETF", "REIT"}
MF_SUBTYPES = {"EQUITY_MF", "DEBT_MF", "LIQUID_FUND", "ARBITRAGE"}


def _kind_for_subtype(subtype: str) -> str | None:
    if subtype in STOCK_SUBTYPES:
        return "STOCK"
    if subtype in MF_SUBTYPES:
        return "MF"
    return None


def forward(apps, schema_editor):
    Asset = apps.get_model("core", "Asset")
    Instrument = apps.get_model("core", "Instrument")

    for asset in Asset.objects.filter(instrument__isnull=True).iterator():
        kind = _kind_for_subtype(asset.subtype)
        if kind is None:
            continue
        symbol = (asset.instrument_symbol or "").strip()
        instrument = None
        if symbol:
            instrument = Instrument.objects.filter(
                profile_id=asset.profile_id,
                exchange_symbol=symbol,
            ).first()
        if instrument is None:
            instrument = Instrument.objects.create(
                profile_id=asset.profile_id,
                isin="",
                exchange_symbol=symbol,
                name=asset.name,
                kind=kind,
                currency=asset.currency or "INR",
                needs_review=True,
            )
        asset.instrument = instrument
        asset.save(update_fields=["instrument"])


def backward(apps, schema_editor):
    Asset = apps.get_model("core", "Asset")
    Asset.objects.exclude(instrument__isnull=True).update(instrument=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_brokeraccount_instrument_dividendrecord_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]

"""Tighten ``DividendRecord`` and ``CorporateAction`` to require a broker account.

Every dividend and corporate action we ingest comes from a broker
statement, and every broker statement (Zerodha XLSX, Chola PDF) carries a
client/account identifier. Making ``broker_account`` non-nullable
matches reality and unblocks per-account dedup.

Schema changes:

* ``DividendSource``: drop ``MANUAL`` and ``AMFI_IDCW`` from choices; the
  app no longer supports broker-less dividend rows.
* ``DividendRecord.broker_account``: ``null=False`` and
  ``on_delete=PROTECT`` (was ``SET_NULL``). The dedup unique constraint
  becomes ``(profile, broker_account, instrument, ex_date,
  amount_gross)`` so the same dividend reported by two brokers (because
  the user holds the ISIN in both demats) survives as two rows.
* ``CorporateAction.broker_account``: ``null=False`` and
  ``on_delete=PROTECT``. The dedup unique constraint becomes
  ``(broker_account, instrument, action_type, ex_date)`` for the same
  reason -- per-account ``units_added`` is independent and would be lost
  by a global key.

This migration assumes no NULL ``broker_account`` rows exist (the import
service has always populated it). If the dataset somehow contains stale
NULL rows, the ``ALTER COLUMN ... NOT NULL`` step will fail loudly --
that is the desired safety behaviour.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_backfill_asset_instrument"),
    ]

    operations = [
        # --- DividendRecord ------------------------------------------------
        migrations.RemoveConstraint(
            model_name="dividendrecord",
            name="uniq_dividend_per_ex_date",
        ),
        migrations.AlterField(
            model_name="dividendrecord",
            name="broker_account",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dividend_records",
                to="core.brokeraccount",
            ),
        ),
        migrations.AlterField(
            model_name="dividendrecord",
            name="source",
            field=models.CharField(
                choices=[
                    ("zerodha_xlsx", "Zerodha XLSX"),
                    ("chola_pdf", "Chola PDF"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="dividendrecord",
            constraint=models.UniqueConstraint(
                fields=(
                    "profile",
                    "broker_account",
                    "instrument",
                    "ex_date",
                    "amount_gross",
                ),
                name="uniq_dividend_per_ex_date",
            ),
        ),
        # --- CorporateAction ----------------------------------------------
        migrations.RemoveConstraint(
            model_name="corporateaction",
            name="uniq_corp_action_per_instrument_date",
        ),
        migrations.AlterField(
            model_name="corporateaction",
            name="broker_account",
            field=models.ForeignKey(
                help_text=(
                    "Demat account this action was reported on. Each broker "
                    "that holds the instrument is recorded separately so "
                    "per-account units_added stays attributable."
                ),
                on_delete=django.db.models.deletion.PROTECT,
                related_name="corporate_actions",
                to="core.brokeraccount",
            ),
        ),
        migrations.AddConstraint(
            model_name="corporateaction",
            constraint=models.UniqueConstraint(
                fields=("broker_account", "instrument", "action_type", "ex_date"),
                name="uniq_corp_action_per_instrument_date",
            ),
        ),
    ]

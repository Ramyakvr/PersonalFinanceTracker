"""Add ``AIONION_XLSX`` to ``DividendSource`` choices.

Aionion adapter is now a real importer (was a stub). The ``source`` field
on ``DividendRecord`` is just a CharField with a ``choices=`` annotation
-- the underlying column is unchanged -- so this migration only records
the schema-state change so future ``makemigrations`` runs stay clean.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_dividend_corpaction_require_broker_account"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dividendrecord",
            name="source",
            field=models.CharField(
                choices=[
                    ("zerodha_xlsx", "Zerodha XLSX"),
                    ("chola_pdf", "Chola PDF"),
                    ("aionion_xlsx", "Aionion XLSX"),
                ],
                max_length=20,
            ),
        ),
    ]

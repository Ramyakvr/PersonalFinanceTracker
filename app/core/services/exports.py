"""Full JSON export + per-table CSV export.

JSON shape:
    {
      "profile": {...},
      "user": {...},
      "assets": [...],
      "liabilities": [...],
      "transactions": [...],
      "categories": [...],
      "goals": [...],
      "snapshots": [...],
      "allocation_targets": [...],
      "essentials": {...} | null,
      "exported_at": "2026-04-19T..."
    }

Decimals serialize as strings so precision is preserved. The JSON export is an
exact round-trip of user-entered data (no computed fields like net_worth).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

from core.models import (
    AllocationTarget,
    Asset,
    Category,
    EssentialsState,
    Goal,
    Liability,
    Profile,
    Snapshot,
    Transaction,
)

CSV_TABLES = ("assets", "liabilities", "transactions", "goals")


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _row_to_dict(instance, fields: list[str]) -> dict:
    return {f: _serialize(getattr(instance, f)) for f in fields}


def export_all(profile: Profile) -> dict:
    user = profile.user
    user_fields = ["username", "base_currency", "theme"]
    profile_fields = ["name", "is_default", "created_at"]
    asset_fields = [
        "id",
        "category",
        "subtype",
        "name",
        "currency",
        "current_value",
        "cost_basis",
        "quantity",
        "unit_price",
        "start_date",
        "maturity_date",
        "interest_rate",
        "geography",
        "sub_class",
        "weight",
        "live_price_enabled",
        "instrument_symbol",
        "notes",
        "exclude_from_allocation",
        "created_at",
        "updated_at",
    ]
    liability_fields = [
        "id",
        "category",
        "name",
        "currency",
        "outstanding_amount",
        "interest_rate",
        "monthly_emi",
        "start_date",
        "notes",
        "created_at",
        "updated_at",
    ]
    tx_fields = [
        "id",
        "type",
        "date",
        "description",
        "amount",
        "currency",
        "notes",
        "created_at",
    ]
    cat_fields = ["id", "type", "name", "is_exempt", "is_custom"]
    goal_fields = [
        "id",
        "name",
        "template_id",
        "target_amount",
        "currency",
        "target_date",
        "linked_asset_class",
        "linked_asset_ids",
        "created_at",
    ]
    snap_fields = [
        "id",
        "taken_at",
        "source",
        "base_currency",
        "net_worth",
        "total_assets",
        "total_liabilities",
        "breakdown_json",
    ]
    alloc_fields = ["id", "preset_name", "percent_by_class"]
    essentials_fields = [
        "emergency_fund_target_months",
        "term_cover_amount",
        "term_cover_target_multiplier",
        "health_cover_amount",
        "health_cover_target",
    ]

    transactions = []
    for tx in Transaction.objects.filter(profile=profile).select_related("category"):
        d = _row_to_dict(tx, tx_fields)
        d["category"] = tx.category.name if tx.category else None
        transactions.append(d)

    categories = [
        _row_to_dict(c, cat_fields) for c in Category.objects.filter(profile__in=[profile, None])
    ]

    essentials = EssentialsState.objects.filter(profile=profile).first()
    essentials_dict = _row_to_dict(essentials, essentials_fields) if essentials else None

    return {
        "schema_version": 1,
        "exported_at": timezone.now().isoformat(),
        "user": _row_to_dict(user, user_fields),
        "profile": _row_to_dict(profile, profile_fields),
        "assets": [_row_to_dict(a, asset_fields) for a in Asset.objects.filter(profile=profile)],
        "liabilities": [
            _row_to_dict(liab, liability_fields)
            for liab in Liability.objects.filter(profile=profile)
        ],
        "transactions": transactions,
        "categories": categories,
        "goals": [_row_to_dict(g, goal_fields) for g in Goal.objects.filter(profile=profile)],
        "snapshots": [
            _row_to_dict(s, snap_fields) for s in Snapshot.objects.filter(profile=profile)
        ],
        "allocation_targets": [
            _row_to_dict(a, alloc_fields) for a in AllocationTarget.objects.filter(profile=profile)
        ],
        "essentials": essentials_dict,
    }


def export_csv(profile: Profile, table: str) -> str:
    """Serialize a single table to CSV. Raises ValueError for unknown table."""
    if table not in CSV_TABLES:
        raise ValueError(f"Unknown table: {table}")
    buf = io.StringIO()

    if table == "assets":
        fieldnames = [
            "name",
            "category",
            "subtype",
            "currency",
            "current_value",
            "cost_basis",
            "quantity",
            "notes",
            "exclude_from_allocation",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for a in Asset.objects.filter(profile=profile):
            writer.writerow({f: _serialize(getattr(a, f)) for f in fieldnames})

    elif table == "liabilities":
        fieldnames = [
            "name",
            "category",
            "currency",
            "outstanding_amount",
            "interest_rate",
            "monthly_emi",
            "start_date",
            "notes",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for lob in Liability.objects.filter(profile=profile):
            writer.writerow({f: _serialize(getattr(lob, f)) for f in fieldnames})

    elif table == "transactions":
        fieldnames = [
            "date",
            "type",
            "category",
            "description",
            "amount",
            "currency",
            "notes",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for tx in Transaction.objects.filter(profile=profile).select_related("category"):
            writer.writerow(
                {
                    "date": tx.date.isoformat(),
                    "type": tx.type,
                    "category": tx.category.name if tx.category else "",
                    "description": tx.description,
                    "amount": _serialize(tx.amount),
                    "currency": tx.currency,
                    "notes": tx.notes,
                }
            )

    else:  # goals
        fieldnames = [
            "name",
            "template_id",
            "target_amount",
            "currency",
            "target_date",
            "linked_asset_class",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for g in Goal.objects.filter(profile=profile):
            writer.writerow({f: _serialize(getattr(g, f)) for f in fieldnames})

    return buf.getvalue()


def wipe_data(profile: Profile) -> dict:
    """Remove every transactional row for this profile. Preserves User + Profile + system categories.

    Returns a dict of row counts deleted, for the confirmation flash.
    """
    counts = {
        "assets": Asset.objects.filter(profile=profile).count(),
        "liabilities": Liability.objects.filter(profile=profile).count(),
        "transactions": Transaction.objects.filter(profile=profile).count(),
        "goals": Goal.objects.filter(profile=profile).count(),
        "snapshots": Snapshot.objects.filter(profile=profile).count(),
        "categories": Category.objects.filter(profile=profile, is_custom=True).count(),
        "allocation_targets": AllocationTarget.objects.filter(profile=profile).count(),
    }
    Asset.objects.filter(profile=profile).delete()
    Liability.objects.filter(profile=profile).delete()
    Transaction.objects.filter(profile=profile).delete()
    Goal.objects.filter(profile=profile).delete()
    Snapshot.objects.filter(profile=profile).delete()
    Category.objects.filter(profile=profile, is_custom=True).delete()
    AllocationTarget.objects.filter(profile=profile).delete()
    return counts

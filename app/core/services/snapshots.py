"""Snapshots are immutable. Write once (manual or nightly auto), read forever.

`breakdown_json` contains the serialized allocation + liabilities at snapshot time so that
rebasing the UI (changing base currency, tweaking target) never rewrites history.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from core.models import Liability, Profile, Snapshot, SnapshotSource
from core.services.allocation import compute_allocation
from core.services.networth import compute_net_worth


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _build_breakdown(profile: Profile) -> dict[str, Any]:
    nw = compute_net_worth(profile)
    alloc = compute_allocation(profile)
    liabilities = [
        {
            "name": liab.name,
            "category": liab.category,
            "outstanding": _decimal_to_str(liab.outstanding_amount),
            "currency": liab.currency,
        }
        for liab in Liability.objects.filter(profile=profile).only(
            "name", "category", "outstanding_amount", "currency"
        )
    ]
    return {
        "base_currency": nw.base_currency,
        "by_asset_category": {k: _decimal_to_str(v) for k, v in nw.by_asset_category.items()},
        "top_holdings": [
            {
                "id": h["id"],
                "name": h["name"],
                "category": h["category"],
                "value": _decimal_to_str(h["value"]),
                "percent": _decimal_to_str(h["percent"]),
            }
            for h in nw.top_holdings
        ],
        "allocation": [
            {
                "key": r.key,
                "label": r.label,
                "actual_value": _decimal_to_str(r.actual_value),
                "actual_pct": _decimal_to_str(r.actual_pct),
                "target_pct": _decimal_to_str(r.target_pct),
            }
            for r in alloc.rows
        ],
        "liabilities": liabilities,
        "conversion_issues": nw.conversion_issues,
    }


def take_snapshot(profile: Profile, *, source: str = SnapshotSource.MANUAL) -> Snapshot:
    """Compute + persist. Values are frozen into `breakdown_json` at write time."""
    nw = compute_net_worth(profile)
    return Snapshot.objects.create(
        profile=profile,
        source=source,
        base_currency=nw.base_currency,
        net_worth=nw.net_worth,
        total_assets=nw.total_assets,
        total_liabilities=nw.total_liabilities,
        breakdown_json=_build_breakdown(profile),
    )


def list_snapshots(profile: Profile) -> QuerySet[Snapshot]:
    return Snapshot.objects.filter(profile=profile).order_by("-taken_at")


def snapshot_series(profile: Profile, *, window: str = "6m") -> list[dict[str, Any]]:
    """Return ordered (oldest -> newest) points for the snapshot line chart.

    `window` accepts "1m", "6m", "1y", "all".
    """
    since = _window_start(window)
    qs = Snapshot.objects.filter(profile=profile)
    if since is not None:
        qs = qs.filter(taken_at__gte=since)
    return [
        {
            "taken_at": s.taken_at.isoformat(),
            "taken_on": s.taken_at.date().isoformat(),
            "source": s.source,
            "net_worth": str(s.net_worth),
            "total_assets": str(s.total_assets),
            "total_liabilities": str(s.total_liabilities),
        }
        for s in qs.order_by("taken_at")
    ]


def _window_start(window: str) -> datetime | None:
    from django.utils import timezone

    now = timezone.now()
    if window == "1m":
        return now - timedelta(days=30)
    if window == "6m":
        return now - timedelta(days=183)
    if window == "1y":
        return now - timedelta(days=365)
    return None


# ---------------------------------------------------------------------------
# Nightly auto-snapshot task (django-q2 entrypoint)
# ---------------------------------------------------------------------------

AUTO_MIN_GAP_HOURS = 18


def auto_snapshot_all() -> dict[str, int]:
    """Run one auto snapshot per default profile, skipping any that were snapshotted recently.

    Safe to run via django-q2 scheduler or `manage.py shell`. Idempotent within AUTO_MIN_GAP_HOURS.
    """
    from django.utils import timezone

    now = timezone.now()
    cutoff = now - timedelta(hours=AUTO_MIN_GAP_HOURS)
    created = 0
    skipped = 0
    for profile in Profile.objects.filter(is_default=True).select_related("user"):
        recent = (
            Snapshot.objects.filter(profile=profile, taken_at__gte=cutoff)
            .order_by("-taken_at")
            .first()
        )
        if recent is not None:
            skipped += 1
            continue
        take_snapshot(profile, source=SnapshotSource.AUTO)
        created += 1
    return {"created": created, "skipped": skipped}


def first_snapshot_on_or_after(profile: Profile, target: date) -> Snapshot | None:
    return (
        Snapshot.objects.filter(profile=profile, taken_at__date__gte=target)
        .order_by("taken_at")
        .first()
    )

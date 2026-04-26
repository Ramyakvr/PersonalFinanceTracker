"""Actual vs Target allocation + Monthly SIP plan.

Actual allocation excludes assets flagged `exclude_from_allocation=True`.
Target allocation is the default `AllocationTarget` for the profile.

Keys are the `AssetCategory` enum values. A `label_for` helper is exposed so templates can
render without reaching into the model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from core.models import AllocationTarget, Asset, AssetCategory, Profile
from core.money import FxRateMissingError, to_base_currency

ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")


def _label(key: str) -> str:
    return dict(AssetCategory.choices).get(key, key)


@dataclass
class AllocationRow:
    key: str
    label: str
    actual_value: Decimal
    actual_pct: Decimal
    target_pct: Decimal

    @property
    def delta_pct(self) -> Decimal:
        return self.actual_pct - self.target_pct


@dataclass
class Allocation:
    base_currency: str
    rows: list[AllocationRow] = field(default_factory=list)
    total_value: Decimal = ZERO
    conversion_issues: list[str] = field(default_factory=list)

    @property
    def has_target(self) -> bool:
        return any(r.target_pct > ZERO for r in self.rows)


def _get_target_map(profile: Profile) -> dict[str, Decimal]:
    target = AllocationTarget.objects.filter(profile=profile).order_by("-id").first()
    if not target:
        return {}
    return {k: Decimal(str(v)) for k, v in (target.percent_by_class or {}).items()}


def compute_allocation(profile: Profile) -> Allocation:
    base = profile.user.base_currency
    alloc = Allocation(base_currency=base)

    # Sum actuals by asset category, skipping exclude_from_allocation rows.
    actual: dict[str, Decimal] = {}
    for a in Asset.objects.filter(profile=profile, exclude_from_allocation=False).only(
        "category", "currency", "current_value"
    ):
        try:
            v = to_base_currency(a.current_value, a.currency, base, user=profile.user)
        except FxRateMissingError as exc:
            alloc.conversion_issues.append(str(exc))
            continue
        actual[a.category] = actual.get(a.category, ZERO) + v

    total = sum(actual.values(), ZERO)
    alloc.total_value = total
    target_map = _get_target_map(profile)

    keys = set(actual.keys()) | set(target_map.keys())
    ordered = [k for k, _ in AssetCategory.choices if k in keys]
    for k in keys:
        if k not in ordered:
            ordered.append(k)

    for k in ordered:
        actual_value = actual.get(k, ZERO)
        actual_pct = (actual_value / total * ONE_HUNDRED) if total > ZERO else ZERO
        alloc.rows.append(
            AllocationRow(
                key=k,
                label=_label(k),
                actual_value=actual_value,
                actual_pct=actual_pct,
                target_pct=target_map.get(k, ZERO),
            )
        )
    return alloc


def monthly_sip_plan(
    alloc: Allocation, *, monthly_budget: Decimal = Decimal("28000")
) -> list[dict]:
    """Split a monthly savings budget across target-weighted classes.

    Real-Estate gets a "lumpsum" label since you can't SIP into it.
    `monthly_budget` is a reasonable default until we wire it into Settings.
    """
    total_target = sum((r.target_pct for r in alloc.rows), ZERO)
    if total_target <= ZERO:
        return []

    plan = []
    for r in alloc.rows:
        if r.target_pct <= ZERO:
            continue
        if r.key == AssetCategory.REAL_ESTATE:
            plan.append({"key": r.key, "label": r.label, "amount": ZERO, "note": "lumpsum"})
            continue
        share = (r.target_pct / total_target) * monthly_budget
        plan.append({"key": r.key, "label": r.label, "amount": share, "note": ""})
    return plan

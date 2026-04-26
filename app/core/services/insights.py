"""Rule-based insights for the dashboard.

No LLM — just deterministic checks over the same services that power the KPIs. Each rule
returns zero or one `Insight`. Compose via `rule_based_insights`.

Rules:
1. Spend up in a category vs last month.
2. Over-weight on a given allocation class vs target.
3. Emergency-fund coverage below target.
4. CTA: missing term-insurance cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from core.models import EssentialsState, Profile, Transaction, TxType
from core.services.allocation import Allocation
from core.services.cashflow import cashflow
from core.services.networth import NetWorth
from core.services.periods import period_range

ZERO = Decimal("0")


@dataclass
class Insight:
    kind: str  # "info" | "warn" | "cta"
    text: str


def _category_spend(profile: Profile, d_from: date, d_to: date) -> dict[str, Decimal]:
    rows = (
        Transaction.objects.filter(
            profile=profile,
            type=TxType.EXPENSE,
            date__gte=d_from,
            date__lte=d_to,
            currency=profile.user.base_currency,
            category__is_exempt=False,
        )
        .values("category__name")
        .annotate(total=Sum("amount"))
    )
    return {r["category__name"]: r["total"] or ZERO for r in rows}


def _spend_change(profile: Profile) -> Insight | None:
    this_from, this_to = period_range("this_month")
    last_from, last_to = period_range("last_month")
    if not this_from or not last_from:
        return None
    now_spend = _category_spend(profile, this_from, this_to)
    prev_spend = _category_spend(profile, last_from, last_to)
    worst: tuple[str, Decimal] | None = None
    for name, now_amt in now_spend.items():
        prev_amt = prev_spend.get(name, ZERO)
        if prev_amt <= ZERO:
            continue
        delta = (now_amt - prev_amt) / prev_amt * Decimal("100")
        if delta >= Decimal("20") and (worst is None or delta > worst[1]):
            worst = (name, delta)
    if not worst:
        return None
    return Insight(
        kind="warn",
        text=f"Spend in {worst[0]} up {worst[1]:.0f}% vs last month.",
    )


def _allocation_drift(alloc: Allocation) -> Insight | None:
    if not alloc.has_target:
        return None
    worst: tuple[str, Decimal] | None = None
    for row in alloc.rows:
        if row.target_pct <= ZERO:
            continue
        drift = row.actual_pct - row.target_pct
        if abs(drift) >= Decimal("5") and (worst is None or abs(drift) > abs(worst[1])):
            worst = (row.label, drift)
    if not worst:
        return None
    label, drift = worst
    direction = "over-weight" if drift > 0 else "under-weight"
    return Insight(
        kind="warn",
        text=f"You are {abs(drift):.0f}% {direction} on {label} relative to target.",
    )


def _emergency_fund(profile: Profile, nw: NetWorth) -> Insight | None:
    from core.models import AssetCategory

    try:
        essentials = profile.essentials
    except EssentialsState.DoesNotExist:
        return None
    cash = nw.by_asset_category.get(AssetCategory.CASH, ZERO)
    # Monthly expense from last month; fall back to this-month expense.
    last_from, last_to = period_range("last_month")
    this_from, this_to = period_range("this_month")
    monthly_expense = ZERO
    if last_from and last_to:
        monthly_expense = cashflow(profile, date_from=last_from, date_to=last_to).expense
    if monthly_expense <= ZERO and this_from and this_to:
        monthly_expense = cashflow(profile, date_from=this_from, date_to=this_to).expense
    if monthly_expense <= ZERO:
        return None
    months_covered = cash / monthly_expense
    target = essentials.emergency_fund_target_months
    if months_covered >= target:
        return None
    return Insight(
        kind="warn",
        text=f"Emergency fund covers {months_covered:.1f} months — target is {target}.",
    )


def _term_cover_cta(profile: Profile) -> Insight | None:
    try:
        essentials = profile.essentials
    except EssentialsState.DoesNotExist:
        return None
    if essentials.term_cover_amount and essentials.term_cover_amount > ZERO:
        return None
    return Insight(
        kind="cta",
        text="Add your term-insurance cover to score Essentials.",
    )


def rule_based_insights(
    profile: Profile, *, net_worth: NetWorth, allocation: Allocation
) -> list[Insight]:
    hits: list[Insight] = []
    for rule in (
        lambda: _spend_change(profile),
        lambda: _allocation_drift(allocation),
        lambda: _emergency_fund(profile, net_worth),
        lambda: _term_cover_cta(profile),
    ):
        insight = rule()
        if insight is not None:
            hits.append(insight)
    return hits

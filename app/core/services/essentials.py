"""Essentials: 4-card financial health check.

Scoring is deterministic, not opinionated. Each card returns a 0-100 sub-score; the overall
score is their average. Subscores saturate at 100 so having "more than enough" of one item
doesn't distort the headline.

Cards (see wireframe `10-essentials.html`):
    1. Emergency Fund   = (cash assets) / (avg monthly expense)    target = N months
    2. Savings Rate     = (income − expense) / income              target = 30%+
    3. Term Insurance   = cover / (annual income × multiplier)     target = cover == target
    4. Health Insurance = health_cover_amount / health_cover_target target = 100%
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from core.models import Asset, AssetCategory, EssentialsState, Profile, Transaction, TxType
from core.services.cashflow import cashflow
from core.services.periods import period_range

ZERO = Decimal("0")


@dataclass
class Card:
    key: str
    label: str
    current_text: str
    target_text: str
    progress_pct: Decimal  # 0..100, clamped
    score: Decimal  # 0..100
    hint: str


@dataclass
class EssentialsReport:
    overall_score: Decimal
    cards: list[Card]


def _cash_total(profile: Profile) -> Decimal:
    from core.money import FxRateMissingError, to_base_currency

    base = profile.user.base_currency
    total = ZERO
    for a in Asset.objects.filter(profile=profile, category=AssetCategory.CASH).only(
        "currency", "current_value"
    ):
        try:
            total += to_base_currency(a.current_value, a.currency, base, user=profile.user)
        except FxRateMissingError:
            continue
    return total


def _avg_monthly_expense(profile: Profile) -> Decimal:
    """Average non-exempt expense over the last 3 completed months in base currency.

    Falls back to last-month only, then this-month, so a brand-new profile still gets a
    meaningful signal.
    """
    today = date.today()
    # Last 3 completed months = today minus 90 days, truncated.
    end = today.replace(day=1) - timedelta(days=1)
    start = (end.replace(day=1) - timedelta(days=62)).replace(day=1)
    qs = Transaction.objects.filter(
        profile=profile,
        type=TxType.EXPENSE,
        date__gte=start,
        date__lte=end,
        currency=profile.user.base_currency,
        category__is_exempt=False,
    )
    total = qs.aggregate(total=Sum("amount")).get("total") or ZERO
    months = max(1, _month_diff(start, end) + 1)
    if total > ZERO:
        return total / Decimal(months)

    last_from, last_to = period_range("last_month")
    if last_from and last_to:
        cf = cashflow(profile, date_from=last_from, date_to=last_to)
        if cf.expense > ZERO:
            return cf.expense

    this_from, this_to = period_range("this_month")
    if this_from and this_to:
        cf = cashflow(profile, date_from=this_from, date_to=this_to)
        return cf.expense
    return ZERO


def _annual_income(profile: Profile) -> Decimal:
    """Trailing 12 months of base-currency income across non-exempt categories."""
    today = date.today()
    start = today - timedelta(days=365)
    qs = Transaction.objects.filter(
        profile=profile,
        type=TxType.INCOME,
        date__gte=start,
        date__lte=today,
        currency=profile.user.base_currency,
        category__is_exempt=False,
    )
    return qs.aggregate(total=Sum("amount")).get("total") or ZERO


def _month_diff(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def _clamp_pct(value: Decimal) -> Decimal:
    if value < ZERO:
        return ZERO
    if value > Decimal("100"):
        return Decimal("100")
    return value


def _format_money(value: Decimal, ccy: str) -> str:
    v = value if isinstance(value, Decimal) else Decimal(value)
    return f"{ccy} {v.quantize(Decimal('1')):,}"


def compute_essentials(profile: Profile) -> EssentialsReport:
    essentials, _ = EssentialsState.objects.get_or_create(profile=profile)
    ccy = profile.user.base_currency

    cash = _cash_total(profile)
    monthly_expense = _avg_monthly_expense(profile)
    months_covered = (cash / monthly_expense) if monthly_expense > ZERO else ZERO
    ef_target = Decimal(essentials.emergency_fund_target_months)
    ef_progress = (
        (months_covered / ef_target * Decimal("100")) if ef_target > ZERO else Decimal("100")
    )
    ef_card = Card(
        key="emergency_fund",
        label="Emergency Fund",
        current_text=f"{months_covered:.1f} months",
        target_text=f"{int(ef_target)} months",
        progress_pct=_clamp_pct(ef_progress),
        score=_clamp_pct(ef_progress),
        hint="(Cash assets) / (avg monthly expense)",
    )

    last_from, last_to = period_range("last_month")
    sr_current = ZERO
    if last_from and last_to:
        cf = cashflow(profile, date_from=last_from, date_to=last_to)
        if cf.income > ZERO:
            sr_current = cf.net / cf.income * Decimal("100")
    sr_target = Decimal("30")
    sr_progress = (sr_current / sr_target * Decimal("100")) if sr_target > ZERO else ZERO
    sr_card = Card(
        key="savings_rate",
        label="Savings Rate",
        current_text=f"{sr_current:.0f}%",
        target_text=f"{int(sr_target)}%+",
        progress_pct=_clamp_pct(sr_progress),
        score=_clamp_pct(sr_progress),
        hint="(Income − Expenses) / Income · last month",
    )

    annual_income = _annual_income(profile)
    term_target = annual_income * Decimal(essentials.term_cover_target_multiplier)
    term_cover = essentials.term_cover_amount or ZERO
    term_progress = (term_cover / term_target * Decimal("100")) if term_target > ZERO else ZERO
    term_card = Card(
        key="term_insurance",
        label="Term Insurance",
        current_text=_format_money(term_cover, ccy),
        target_text=_format_money(term_target, ccy),
        progress_pct=_clamp_pct(term_progress),
        score=_clamp_pct(term_progress),
        hint=f"Cover / (annual income × {essentials.term_cover_target_multiplier})",
    )

    health_cover = essentials.health_cover_amount or ZERO
    health_target = essentials.health_cover_target or ZERO
    health_progress = (
        (health_cover / health_target * Decimal("100")) if health_target > ZERO else ZERO
    )
    health_card = Card(
        key="health_insurance",
        label="Health Insurance",
        current_text=_format_money(health_cover, ccy),
        target_text=_format_money(health_target, ccy),
        progress_pct=_clamp_pct(health_progress),
        score=_clamp_pct(health_progress),
        hint="Cover vs user-set target",
    )

    cards = [ef_card, sr_card, term_card, health_card]
    overall = sum((c.score for c in cards), ZERO) / Decimal(len(cards))
    return EssentialsReport(overall_score=overall, cards=cards)


def update_essentials(profile: Profile, **fields) -> EssentialsState:
    essentials, _ = EssentialsState.objects.get_or_create(profile=profile)
    for key, value in fields.items():
        if value is None:
            continue
        setattr(essentials, key, value)
    essentials.save()
    return essentials

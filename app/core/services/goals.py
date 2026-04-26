"""Goal CRUD + progress + projection math.

Progress depends on the goal's `linked_asset_class`:

- ``NET_WORTH``    — total assets − total liabilities, in base currency.
- any ``AssetCategory`` key — sum of that category in base currency.
- Additionally, if ``linked_asset_ids`` is populated, only those specific assets count.

Projection uses the standard compound-growth formula:

    FV = PV × (1 + r) ** years

where `r` is a "real" (inflation-adjusted) annual return. Default `r` = 7% which is a
conservative equity-heavy pick for India; callers can override per-goal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.models import Asset, AssetCategory, Goal, Profile, Tag
from core.money import FxRateMissingError, to_base_currency
from core.services.networth import compute_net_worth

ZERO = Decimal("0")
DEFAULT_REAL_RETURN = Decimal("0.07")


GOAL_TEMPLATES = [
    ("", "Custom"),
    ("RETIREMENT", "Retirement"),
    ("HOME_DOWN_PAYMENT", "Home Down-payment"),
    ("CHILD_EDUCATION", "Child Education"),
    ("EMERGENCY", "Emergency Fund"),
    ("TRAVEL", "Travel / Vacation"),
    ("VEHICLE", "Vehicle"),
]

# Tracks. "NET_WORTH" is the sentinel for "all assets, net of liabilities".
TRACK_CHOICES = [("NET_WORTH", "Net Worth (all assets)")] + [
    (k, v) for k, v in AssetCategory.choices
]


@dataclass
class GoalProgress:
    goal: Goal
    current: Decimal
    target: Decimal
    percent: Decimal
    months_left: int
    monthly_required: Decimal
    status: str  # "on_track" | "behind" | "done"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_goals(profile: Profile):
    return Goal.objects.filter(profile=profile).order_by("target_date", "id")


def create_goal(profile: Profile, *, tags: list[Tag] | None = None, **fields) -> Goal:
    goal = Goal.objects.create(profile=profile, **fields)
    return goal


def update_goal(goal: Goal, **fields) -> Goal:
    for key, value in fields.items():
        setattr(goal, key, value)
    goal.save()
    return goal


def delete_goal(goal: Goal) -> None:
    goal.delete()


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def _category_value(profile: Profile, category: str) -> Decimal:
    base = profile.user.base_currency
    total = ZERO
    for a in Asset.objects.filter(profile=profile, category=category).only(
        "currency", "current_value"
    ):
        try:
            total += to_base_currency(a.current_value, a.currency, base, user=profile.user)
        except FxRateMissingError:
            continue
    return total


def _specific_assets_value(profile: Profile, asset_ids: list[int]) -> Decimal:
    base = profile.user.base_currency
    total = ZERO
    for a in Asset.objects.filter(profile=profile, id__in=asset_ids).only(
        "currency", "current_value"
    ):
        try:
            total += to_base_currency(a.current_value, a.currency, base, user=profile.user)
        except FxRateMissingError:
            continue
    return total


def compute_current_value(profile: Profile, goal: Goal) -> Decimal:
    """Current tracked value for the goal, in base currency."""
    if goal.linked_asset_ids:
        return _specific_assets_value(profile, list(goal.linked_asset_ids))
    if goal.linked_asset_class == "NET_WORTH":
        return compute_net_worth(profile).net_worth
    return _category_value(profile, goal.linked_asset_class)


def _months_between(today: date, target: date) -> int:
    if target <= today:
        return 0
    return max(1, (target.year - today.year) * 12 + (target.month - today.month))


def progress(profile: Profile, goal: Goal, *, today: date | None = None) -> GoalProgress:
    today = today or date.today()
    current = compute_current_value(profile, goal)
    target = goal.target_amount
    percent = (current / target * Decimal("100")) if target > ZERO else ZERO
    months_left = _months_between(today, goal.target_date)

    remaining = max(target - current, ZERO)
    monthly_required = (remaining / Decimal(months_left)) if months_left > 0 else remaining

    if current >= target:
        status = "done"
    elif months_left == 0 and current < target:
        status = "behind"
    else:
        # "on track" heuristic: if current >= pro-rated linear expectation, on track.
        # Very simple — refine later.
        elapsed_ratio = _elapsed_ratio(goal, today)
        expected = target * elapsed_ratio
        status = "on_track" if current >= expected else "behind"

    return GoalProgress(
        goal=goal,
        current=current,
        target=target,
        percent=percent,
        months_left=months_left,
        monthly_required=monthly_required,
        status=status,
    )


def _elapsed_ratio(goal: Goal, today: date) -> Decimal:
    """Fraction of the goal horizon that has elapsed, clamped to [0, 1]."""
    created = goal.created_at.date() if goal.created_at else today
    total_days = (goal.target_date - created).days
    if total_days <= 0:
        return Decimal("1")
    elapsed_days = max(0, (today - created).days)
    return min(Decimal(elapsed_days) / Decimal(total_days), Decimal("1"))


# ---------------------------------------------------------------------------
# Projection / inflation helpers
# ---------------------------------------------------------------------------


def future_value(
    present_value: Decimal, years: Decimal | int, real_return: Decimal | None = None
) -> Decimal:
    """FV = PV × (1 + r) ** years. Decimal-safe."""
    r = real_return if real_return is not None else DEFAULT_REAL_RETURN
    years_dec = Decimal(years)
    # Decimal has no builtin power-of-decimal; iterate when years is a whole number,
    # otherwise fall back through Decimal.ln / exp for fractional years.
    if years_dec == years_dec.to_integral_value():
        factor = Decimal("1")
        for _ in range(int(years_dec)):
            factor *= Decimal("1") + r
        return present_value * factor
    # Fractional-year fallback via floats -> Decimal (acceptable for inflation previews).
    return present_value * (Decimal(str((1 + float(r)) ** float(years_dec))))


def inflate(amount_today: Decimal, years: int, inflation: Decimal = Decimal("0.06")) -> Decimal:
    """Inflate today's cost by `inflation` p.a. for `years` years. Used for the calculator popup."""
    return future_value(amount_today, years, inflation)

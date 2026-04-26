"""Net-worth computation in the user's base currency.

Every Asset/Liability is converted through `core.money.to_base_currency` using the cached
FxRate rows. Missing rates fall through as `conversion_issues` so the UI can warn the user
rather than silently zero the row.

Returns plain dicts (not ORM rows) so template callers stay decoupled from the schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from core.models import Asset, Liability, Profile
from core.money import FxRateMissingError, to_base_currency

ZERO = Decimal("0")


@dataclass
class NetWorth:
    base_currency: str
    total_assets: Decimal = ZERO
    total_liabilities: Decimal = ZERO
    by_asset_category: dict[str, Decimal] = field(default_factory=dict)
    top_holdings: list[dict] = field(default_factory=list)
    conversion_issues: list[str] = field(default_factory=list)

    @property
    def net_worth(self) -> Decimal:
        return self.total_assets - self.total_liabilities


def _convert(amount: Decimal, from_ccy: str, base: str, *, user, issues: list[str]) -> Decimal:
    try:
        return to_base_currency(amount, from_ccy, base, user=user)
    except FxRateMissingError as exc:
        issues.append(str(exc))
        return ZERO


def compute_net_worth(profile: Profile, *, top_n: int = 5) -> NetWorth:
    """Aggregate assets and liabilities into a NetWorth dataclass in base currency."""
    base = profile.user.base_currency
    result = NetWorth(base_currency=base)

    # Holdings
    holdings: list[tuple[Asset, Decimal]] = []
    for asset in Asset.objects.filter(profile=profile).only(
        "id", "name", "category", "currency", "current_value"
    ):
        converted = _convert(
            asset.current_value,
            asset.currency,
            base,
            user=profile.user,
            issues=result.conversion_issues,
        )
        result.total_assets += converted
        result.by_asset_category[asset.category] = (
            result.by_asset_category.get(asset.category, ZERO) + converted
        )
        holdings.append((asset, converted))

    # Liabilities
    for liab in Liability.objects.filter(profile=profile).only(
        "id", "currency", "outstanding_amount"
    ):
        converted = _convert(
            liab.outstanding_amount,
            liab.currency,
            base,
            user=profile.user,
            issues=result.conversion_issues,
        )
        result.total_liabilities += converted

    # Top holdings as plain dicts (templates don't need the ORM row).
    holdings.sort(key=lambda pair: pair[1], reverse=True)
    total_for_pct = result.total_assets if result.total_assets > ZERO else Decimal("1")
    result.top_holdings = [
        {
            "id": a.id,
            "name": a.name,
            "category": a.category,
            "value": v,
            "percent": (v / total_for_pct) * Decimal("100"),
        }
        for a, v in holdings[:top_n]
    ]

    return result


def invested_amount(profile: Profile) -> Decimal:
    """Sum of `cost_basis` across assets that declare one. Used for the 'Invested' KPI."""
    base = profile.user.base_currency
    total = ZERO
    for asset in Asset.objects.filter(profile=profile).only("currency", "cost_basis"):
        if asset.cost_basis is None:
            continue
        try:
            total += to_base_currency(asset.cost_basis, asset.currency, base, user=profile.user)
        except FxRateMissingError:
            continue
    return total

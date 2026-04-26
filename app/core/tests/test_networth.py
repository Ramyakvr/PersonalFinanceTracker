from decimal import Decimal

import pytest

from core.models import Asset, AssetCategory, FxRate, Liability, LiabilityCategory, Profile, User
from core.services.networth import compute_net_worth, invested_amount


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.mark.django_db
def test_net_worth_zero_when_empty(profile):
    nw = compute_net_worth(profile)
    assert nw.net_worth == Decimal("0")
    assert nw.total_assets == Decimal("0")
    assert nw.total_liabilities == Decimal("0")
    assert nw.top_holdings == []


@pytest.mark.django_db
def test_net_worth_same_currency(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("100000"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="HDFC SB",
        currency="INR",
        current_value=Decimal("50000"),
    )
    Liability.objects.create(
        profile=profile,
        category=LiabilityCategory.CREDIT_CARD,
        name="HDFC Card",
        currency="INR",
        outstanding_amount=Decimal("20000"),
    )
    nw = compute_net_worth(profile)
    assert nw.total_assets == Decimal("150000")
    assert nw.total_liabilities == Decimal("20000")
    assert nw.net_worth == Decimal("130000")
    assert nw.by_asset_category[AssetCategory.EQUITY] == Decimal("100000")
    assert nw.by_asset_category[AssetCategory.CASH] == Decimal("50000")


@pytest.mark.django_db
def test_net_worth_converts_via_fx(profile):
    FxRate.objects.create(user=profile.user, from_ccy="USD", to_ccy="INR", rate=Decimal("83"))
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="AAPL",
        currency="USD",
        current_value=Decimal("1000"),
    )
    nw = compute_net_worth(profile)
    assert nw.total_assets == Decimal("83000")
    assert nw.conversion_issues == []


@pytest.mark.django_db
def test_net_worth_missing_fx_records_issue(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="AAPL",
        currency="USD",
        current_value=Decimal("1000"),
    )
    nw = compute_net_worth(profile)
    assert nw.total_assets == Decimal("0")
    assert len(nw.conversion_issues) == 1
    assert "USD" in nw.conversion_issues[0]


@pytest.mark.django_db
def test_top_holdings_sorted_by_value(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="A",
        currency="INR",
        current_value=Decimal("100"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="B",
        currency="INR",
        current_value=Decimal("500"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="C",
        currency="INR",
        current_value=Decimal("300"),
    )
    nw = compute_net_worth(profile, top_n=2)
    assert [h["name"] for h in nw.top_holdings] == ["B", "C"]
    assert nw.top_holdings[0]["percent"] == Decimal("500") / Decimal("900") * Decimal("100")


@pytest.mark.django_db
def test_invested_sums_cost_basis(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("200"),
        cost_basis=Decimal("150"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="NoBasis",
        currency="INR",
        current_value=Decimal("400"),
    )
    assert invested_amount(profile) == Decimal("150")

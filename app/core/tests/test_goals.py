from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.models import Asset, AssetCategory, Profile, User
from core.services.goals import (
    DEFAULT_REAL_RETURN,
    compute_current_value,
    create_goal,
    future_value,
    inflate,
    list_goals,
    progress,
    update_goal,
)


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.mark.django_db
def test_create_list_update_goal(profile):
    g = create_goal(
        profile,
        name="Retirement",
        template_id="RETIREMENT",
        target_amount=Decimal("10000000"),
        currency="INR",
        target_date=date(2045, 12, 31),
        linked_asset_class="NET_WORTH",
    )
    assert list(list_goals(profile)) == [g]
    update_goal(g, name="Retirement 2045")
    g.refresh_from_db()
    assert g.name == "Retirement 2045"


@pytest.mark.django_db
def test_progress_uses_net_worth(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("500000"),
    )
    g = create_goal(
        profile,
        name="NW",
        target_amount=Decimal("1000000"),
        currency="INR",
        target_date=date.today() + timedelta(days=365),
        linked_asset_class="NET_WORTH",
    )
    p = progress(profile, g)
    assert p.current == Decimal("500000")
    assert p.target == Decimal("1000000")
    assert p.percent == Decimal("50")


@pytest.mark.django_db
def test_progress_uses_asset_class(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="SB",
        currency="INR",
        current_value=Decimal("60000"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("999999"),
    )
    g = create_goal(
        profile,
        name="EF",
        target_amount=Decimal("120000"),
        currency="INR",
        target_date=date.today() + timedelta(days=180),
        linked_asset_class=AssetCategory.CASH,
    )
    p = progress(profile, g)
    assert p.current == Decimal("60000")  # only CASH counted


@pytest.mark.django_db
def test_progress_uses_specific_assets(profile):
    a1 = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="A",
        currency="INR",
        current_value=Decimal("100"),
    )
    a2 = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="B",
        currency="INR",
        current_value=Decimal("200"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="C",
        currency="INR",
        current_value=Decimal("999"),
    )
    g = create_goal(
        profile,
        name="Child",
        target_amount=Decimal("1000"),
        currency="INR",
        target_date=date.today() + timedelta(days=365),
        linked_asset_class=AssetCategory.EQUITY,
        linked_asset_ids=[a1.id, a2.id],
    )
    assert compute_current_value(profile, g) == Decimal("300")


@pytest.mark.django_db
def test_progress_status_done(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="SB",
        currency="INR",
        current_value=Decimal("1000"),
    )
    g = create_goal(
        profile,
        name="Small",
        target_amount=Decimal("500"),
        currency="INR",
        target_date=date.today() + timedelta(days=30),
        linked_asset_class=AssetCategory.CASH,
    )
    p = progress(profile, g)
    assert p.status == "done"


@pytest.mark.django_db
def test_progress_behind_when_target_passed(profile):
    g = create_goal(
        profile,
        name="OldGoal",
        target_amount=Decimal("1000"),
        currency="INR",
        target_date=date.today() - timedelta(days=10),
        linked_asset_class="NET_WORTH",
    )
    p = progress(profile, g)
    assert p.status == "behind"
    assert p.months_left == 0


def test_future_value_integer_years():
    # 100 @ 10% for 3 years -> 133.1
    assert future_value(Decimal("100"), 3, Decimal("0.10")) == Decimal("133.100")


def test_future_value_default_return():
    # 7% default real return for 10 years
    fv = future_value(Decimal("100"), 10)
    assert fv > Decimal("196")  # (1.07)^10 ≈ 1.967
    assert fv < Decimal("198")
    # Exercise default arg path
    assert Decimal("0.07") == DEFAULT_REAL_RETURN


def test_inflate_is_future_value_wrapper():
    # 6% inflation for 5 years
    assert inflate(Decimal("100"), 5) == future_value(Decimal("100"), 5, Decimal("0.06"))


def test_future_value_fractional_years():
    fv = future_value(Decimal("100"), Decimal("1.5"), Decimal("0.10"))
    # ~100 * 1.1^1.5 ~= 115.37
    assert Decimal("114") < fv < Decimal("117")

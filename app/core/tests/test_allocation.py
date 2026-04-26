from decimal import Decimal

import pytest

from core.models import AllocationTarget, Asset, AssetCategory, Profile, User
from core.services.allocation import compute_allocation, monthly_sip_plan


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    profile = Profile.objects.create(user=user, name="Self", is_default=True)
    AllocationTarget.objects.create(
        profile=profile,
        preset_name="Default",
        percent_by_class={
            "EQUITY": 55,
            "BONDS_DEBT": 20,
            "GOLD": 10,
            "ALTERNATIVES": 10,
            "REAL_ESTATE": 5,
        },
    )
    return profile


@pytest.mark.django_db
def test_allocation_all_zero_when_no_assets(profile):
    alloc = compute_allocation(profile)
    # Target rows still show up so target summary still renders.
    assert alloc.total_value == Decimal("0")
    assert all(r.actual_pct == Decimal("0") for r in alloc.rows)
    assert {r.key for r in alloc.rows} >= {"EQUITY", "BONDS_DEBT"}


@pytest.mark.django_db
def test_allocation_percentages(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="A",
        currency="INR",
        current_value=Decimal("620"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.BONDS_DEBT,
        subtype="BOND",
        name="B",
        currency="INR",
        current_value=Decimal("160"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.GOLD,
        subtype="PHYSICAL_GOLD",
        name="G",
        currency="INR",
        current_value=Decimal("120"),
    )
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.ALTERNATIVES,
        subtype="P2P",
        name="P",
        currency="INR",
        current_value=Decimal("100"),
    )
    alloc = compute_allocation(profile)
    assert alloc.total_value == Decimal("1000")
    by_key = {r.key: r for r in alloc.rows}
    assert by_key["EQUITY"].actual_pct == Decimal("62.0")
    assert by_key["EQUITY"].target_pct == Decimal("55")
    assert by_key["EQUITY"].delta_pct == Decimal("7.0")
    assert by_key["BONDS_DEBT"].actual_pct == Decimal("16.0")
    assert by_key["REAL_ESTATE"].actual_pct == Decimal("0")
    assert by_key["REAL_ESTATE"].target_pct == Decimal("5")


@pytest.mark.django_db
def test_excluded_asset_is_skipped(profile):
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
        category=AssetCategory.GOLD,
        subtype="PHYSICAL_GOLD",
        name="Gift",
        currency="INR",
        current_value=Decimal("9999"),
        exclude_from_allocation=True,
    )
    alloc = compute_allocation(profile)
    assert alloc.total_value == Decimal("100")


@pytest.mark.django_db
def test_sip_plan_weights_real_estate_lumpsum(profile):
    alloc = compute_allocation(profile)
    plan = monthly_sip_plan(alloc, monthly_budget=Decimal("10000"))
    by_key = {p["key"]: p for p in plan}
    # EQUITY=55, DEBT=20, GOLD=10, ALT=10, RE=5 -> sum=100
    assert by_key["EQUITY"]["amount"] == Decimal("5500")
    assert by_key["BONDS_DEBT"]["amount"] == Decimal("2000")
    assert by_key["REAL_ESTATE"]["note"] == "lumpsum"
    assert by_key["REAL_ESTATE"]["amount"] == Decimal("0")


@pytest.mark.django_db
def test_sip_plan_empty_when_no_target(db):
    user = User.objects.create(username="noone", base_currency="INR")
    prof = Profile.objects.create(user=user, name="NoTarget", is_default=False)
    alloc = compute_allocation(prof)
    assert monthly_sip_plan(alloc) == []

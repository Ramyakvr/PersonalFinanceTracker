from decimal import Decimal

import pytest

from core.models import (
    Asset,
    AssetCategory,
    Liability,
    LiabilityCategory,
    Profile,
    Tag,
    User,
)
from core.services import assets as asset_svc
from core.services import liabilities as liability_svc
from core.services.tags import parse_tags, serialize_tags


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.fixture
def other_profile(db):
    user = User.objects.create(username="spouse", base_currency="INR")
    return Profile.objects.create(user=user, name="Spouse", is_default=False)


# --- Tags -----------------------------------------------------------------


@pytest.mark.django_db
def test_parse_tags_dedups_and_creates(profile):
    tags = parse_tags(profile, "tax-saving, long-term, Tax-Saving,  ")
    assert [t.label for t in tags] == ["tax-saving", "long-term"]
    assert Tag.objects.filter(profile=profile).count() == 2


@pytest.mark.django_db
def test_parse_tags_empty_returns_empty(profile):
    assert parse_tags(profile, "") == []
    assert parse_tags(profile, None) == []


@pytest.mark.django_db
def test_parse_tags_reuses_existing(profile):
    Tag.objects.create(profile=profile, label="existing")
    tags = parse_tags(profile, "existing, new")
    labels = {t.label for t in tags}
    assert labels == {"existing", "new"}
    assert Tag.objects.filter(profile=profile).count() == 2


@pytest.mark.django_db
def test_serialize_tags(profile):
    t1 = Tag.objects.create(profile=profile, label="first")
    t2 = Tag.objects.create(profile=profile, label="second")
    assert serialize_tags([t1, t2]) == "first, second"


# --- Assets ---------------------------------------------------------------


@pytest.mark.django_db
def test_create_and_list_asset(profile):
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("245000.00"),
    )
    rows = list(asset_svc.list_assets(profile))
    assert rows == [asset]


@pytest.mark.django_db
def test_list_scopes_to_profile(profile, other_profile):
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        current_value=Decimal("100"),
    )
    asset_svc.create_asset(
        other_profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="TCS",
        current_value=Decimal("200"),
    )
    assert asset_svc.list_assets(profile).count() == 1
    assert asset_svc.list_assets(other_profile).count() == 1


@pytest.mark.django_db
def test_asset_search_filters(profile):
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        instrument_symbol="INFY.NSE",
        current_value=Decimal("100"),
    )
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="TCS",
        instrument_symbol="TCS.NSE",
        current_value=Decimal("200"),
    )
    assert asset_svc.list_assets(profile, search="tcs").count() == 1
    assert asset_svc.list_assets(profile, search="infy.nse").count() == 1


@pytest.mark.django_db
def test_asset_category_filter(profile):
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        current_value=Decimal("100"),
    )
    asset_svc.create_asset(
        profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="HDFC Savings",
        current_value=Decimal("50000"),
    )
    assert asset_svc.list_assets(profile, category=AssetCategory.EQUITY).count() == 1
    assert asset_svc.list_assets(profile, category=AssetCategory.CASH).count() == 1


@pytest.mark.django_db
def test_asset_tag_filter(profile):
    tag_a = Tag.objects.create(profile=profile, label="a")
    tag_b = Tag.objects.create(profile=profile, label="b")
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        current_value=Decimal("100"),
        tags=[tag_a],
    )
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="TCS",
        current_value=Decimal("200"),
        tags=[tag_b],
    )
    rows = list(asset_svc.list_assets(profile, tag_ids=[tag_a.id]))
    assert rows == [asset]


@pytest.mark.django_db
def test_update_asset_replaces_tags(profile):
    tag_keep = Tag.objects.create(profile=profile, label="keep")
    tag_drop = Tag.objects.create(profile=profile, label="drop")
    tag_new = Tag.objects.create(profile=profile, label="new")
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        current_value=Decimal("100"),
        tags=[tag_keep, tag_drop],
    )
    asset_svc.update_asset(asset, tags=[tag_keep, tag_new], name="INFY - Infosys")
    asset.refresh_from_db()
    assert asset.name == "INFY - Infosys"
    assert set(asset.tags.values_list("label", flat=True)) == {"keep", "new"}


@pytest.mark.django_db
def test_delete_asset_removes_row(profile):
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        current_value=Decimal("100"),
    )
    asset_svc.delete_asset(asset)
    assert not Asset.objects.filter(id=asset.id).exists()


@pytest.mark.django_db
def test_distinct_currencies(profile):
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("100"),
    )
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="AAPL",
        currency="USD",
        current_value=Decimal("100"),
    )
    assert asset_svc.distinct_currencies(profile) == ["INR", "USD"]


# --- Liabilities ----------------------------------------------------------


@pytest.mark.django_db
def test_create_and_list_liability(profile):
    liability = liability_svc.create_liability(
        profile,
        category=LiabilityCategory.HOME_LOAN,
        name="Home Loan - SBI",
        currency="INR",
        outstanding_amount=Decimal("4500000"),
        interest_rate=Decimal("8.5"),
        monthly_emi=Decimal("38000"),
    )
    rows = list(liability_svc.list_liabilities(profile))
    assert rows == [liability]


@pytest.mark.django_db
def test_update_delete_liability(profile):
    liability = liability_svc.create_liability(
        profile,
        category=LiabilityCategory.VEHICLE_LOAN,
        name="Car Loan",
        outstanding_amount=Decimal("200000"),
    )
    liability_svc.update_liability(liability, outstanding_amount=Decimal("150000"))
    liability.refresh_from_db()
    assert liability.outstanding_amount == Decimal("150000.0000")
    liability_svc.delete_liability(liability)
    assert not Liability.objects.filter(id=liability.id).exists()

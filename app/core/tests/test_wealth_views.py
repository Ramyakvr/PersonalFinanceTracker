from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from core.models import Asset, AssetCategory, Liability, LiabilityCategory, Profile, User
from core.services import assets as asset_svc
from core.services import liabilities as liability_svc


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.fixture
def client(profile):
    return Client()


# --- Asset list -----------------------------------------------------------


@pytest.mark.django_db
def test_asset_list_empty_state(client):
    response = client.get(reverse("asset_list"))
    assert response.status_code == 200
    assert b"No assets yet" in response.content
    assert b"Add your first asset" in response.content


@pytest.mark.django_db
def test_asset_list_shows_rows(client, profile):
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY Test",
        current_value=Decimal("245000"),
    )
    response = client.get(reverse("asset_list"))
    assert response.status_code == 200
    assert b"INFY Test" in response.content
    assert b"Stocks &amp; Equity" in response.content


@pytest.mark.django_db
def test_asset_list_search_filter(client, profile):
    asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY Test",
        current_value=Decimal("100"),
    )
    asset_svc.create_asset(
        profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="HDFC Savings",
        current_value=Decimal("50000"),
    )
    response = client.get(reverse("asset_list"), {"q": "hdfc"})
    assert response.status_code == 200
    assert b"HDFC Savings" in response.content
    assert b"INFY Test" not in response.content


# --- Asset wizard + create ------------------------------------------------


@pytest.mark.django_db
def test_asset_wizard_step1_shows_8_categories(client):
    response = client.get(reverse("asset_new"))
    assert response.status_code == 200
    for _, label in AssetCategory.choices:
        assert (
            label.encode().replace(b"&", b"&amp;") in response.content
            or label.encode() in response.content
        )


@pytest.mark.django_db
def test_asset_wizard_step2_shows_form(client):
    response = client.get(reverse("asset_new"), {"category": AssetCategory.EQUITY})
    assert response.status_code == 200
    assert b"Direct Stock" in response.content
    assert b"Current Value" in response.content


@pytest.mark.django_db
def test_asset_wizard_unknown_category_redirects(client):
    response = client.get(reverse("asset_new"), {"category": "BOGUS"})
    assert response.status_code == 302


@pytest.mark.django_db
def test_asset_create_via_post(client, profile):
    response = client.post(
        reverse("asset_new") + f"?category={AssetCategory.EQUITY}",
        {
            "category": AssetCategory.EQUITY,
            "subtype": "DIRECT_STOCK",
            "name": "INFY Test",
            "currency": "INR",
            "current_value": "245000.00",
            "tags_raw": "it, long-term",
        },
    )
    assert response.status_code == 302
    asset = Asset.objects.get(name="INFY Test")
    assert asset.profile == profile
    assert asset.subtype == "DIRECT_STOCK"
    assert set(asset.tags.values_list("label", flat=True)) == {"it", "long-term"}


@pytest.mark.django_db
def test_asset_create_rejects_mismatched_subtype(client):
    # EQUITY category with a liability/cash-only subtype should fail.
    response = client.post(
        reverse("asset_new") + f"?category={AssetCategory.EQUITY}",
        {
            "category": AssetCategory.EQUITY,
            "subtype": "SAVINGS",
            "name": "bogus",
            "currency": "INR",
            "current_value": "100",
        },
    )
    # Form renders with errors (200), doesn't redirect.
    assert response.status_code == 200
    assert Asset.objects.count() == 0


@pytest.mark.django_db
def test_asset_save_and_add_redirects_back(client, profile):
    response = client.post(
        reverse("asset_new") + f"?category={AssetCategory.EQUITY}",
        {
            "category": AssetCategory.EQUITY,
            "subtype": "DIRECT_STOCK",
            "name": "INFY First",
            "currency": "INR",
            "current_value": "100",
            "action": "save_and_add",
        },
    )
    assert response.status_code == 302
    assert "asset_new" in response["Location"] or "category=" in response["Location"]


# --- Asset edit + delete --------------------------------------------------


@pytest.mark.django_db
def test_asset_edit_prefills_tags(client, profile):
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY Test",
        current_value=Decimal("100"),
    )
    from core.models import Tag

    t = Tag.objects.create(profile=profile, label="it")
    asset.tags.add(t)

    response = client.get(reverse("asset_edit", args=[asset.id]))
    assert response.status_code == 200
    assert b'value="it"' in response.content


@pytest.mark.django_db
def test_asset_edit_updates_fields(client, profile):
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY Test",
        current_value=Decimal("100"),
    )
    response = client.post(
        reverse("asset_edit", args=[asset.id]),
        {
            "category": AssetCategory.EQUITY,
            "subtype": "DIRECT_STOCK",
            "name": "INFY - Renamed",
            "currency": "INR",
            "current_value": "999",
        },
    )
    assert response.status_code == 302
    asset.refresh_from_db()
    assert asset.name == "INFY - Renamed"


@pytest.mark.django_db
def test_asset_delete_removes(client, profile):
    asset = asset_svc.create_asset(
        profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY Test",
        current_value=Decimal("100"),
    )
    response = client.post(reverse("asset_delete", args=[asset.id]))
    assert response.status_code == 302
    assert not Asset.objects.filter(id=asset.id).exists()


@pytest.mark.django_db
def test_asset_edit_other_profile_404(client, profile):
    other_user = User.objects.create(username="spouse")
    other_profile = Profile.objects.create(user=other_user, name="Spouse")
    asset = asset_svc.create_asset(
        other_profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="Hers",
        current_value=Decimal("100"),
    )
    response = client.get(reverse("asset_edit", args=[asset.id]))
    assert response.status_code == 404


# --- Liability ------------------------------------------------------------


@pytest.mark.django_db
def test_liability_list_empty(client):
    response = client.get(reverse("liability_list"))
    assert response.status_code == 200
    assert b"No liabilities yet" in response.content


@pytest.mark.django_db
def test_liability_wizard_step1(client):
    response = client.get(reverse("liability_new"))
    assert response.status_code == 200
    assert b"Home Loan" in response.content
    assert b"Credit Card" in response.content


@pytest.mark.django_db
def test_liability_create(client, profile):
    response = client.post(
        reverse("liability_new") + f"?category={LiabilityCategory.HOME_LOAN}",
        {
            "category": LiabilityCategory.HOME_LOAN,
            "name": "Home Loan Test",
            "currency": "INR",
            "outstanding_amount": "4500000",
            "interest_rate": "8.5",
            "monthly_emi": "38000",
        },
    )
    assert response.status_code == 302
    assert Liability.objects.filter(name="Home Loan Test").exists()


@pytest.mark.django_db
def test_liability_edit_update(client, profile):
    liability = liability_svc.create_liability(
        profile,
        category=LiabilityCategory.HOME_LOAN,
        name="Home Loan Test",
        outstanding_amount=Decimal("4500000"),
    )
    response = client.post(
        reverse("liability_edit", args=[liability.id]),
        {
            "category": LiabilityCategory.HOME_LOAN,
            "name": "Home Loan - Renamed",
            "currency": "INR",
            "outstanding_amount": "4400000",
        },
    )
    assert response.status_code == 302
    liability.refresh_from_db()
    assert liability.name == "Home Loan - Renamed"


@pytest.mark.django_db
def test_liability_delete(client, profile):
    liability = liability_svc.create_liability(
        profile,
        category=LiabilityCategory.HOME_LOAN,
        name="Home Loan Test",
        outstanding_amount=Decimal("100000"),
    )
    response = client.post(reverse("liability_delete", args=[liability.id]))
    assert response.status_code == 302
    assert not Liability.objects.filter(id=liability.id).exists()

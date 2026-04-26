from decimal import Decimal

import pytest
from django.test import Client

from core.models import (
    AllocationTarget,
    Asset,
    AssetCategory,
    EssentialsState,
    Liability,
    LiabilityCategory,
    Profile,
    User,
)


@pytest.fixture
def seeded(db):
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
    EssentialsState.objects.create(profile=profile)
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("100000"),
    )
    Liability.objects.create(
        profile=profile,
        category=LiabilityCategory.CREDIT_CARD,
        name="Card",
        currency="INR",
        outstanding_amount=Decimal("10000"),
    )
    return profile


@pytest.mark.django_db
def test_dashboard_renders_kpis(seeded):
    response = Client().get("/")
    assert response.status_code == 200
    # Net worth = 100000 - 10000 = 90000 formatted.
    assert b"Net Worth" in response.content
    assert b"INFY" in response.content  # top holding


@pytest.mark.django_db
def test_allocation_page_renders(seeded):
    response = Client().get("/wealth/allocation")
    assert response.status_code == 200
    assert b"Allocation" in response.content
    assert b"Delta" in response.content
    assert b"Monthly SIP Plan" in response.content


@pytest.mark.django_db
def test_snapshots_page_empty(seeded):
    response = Client().get("/wealth/snapshots")
    assert response.status_code == 200
    assert b"0 snapshots" in response.content


@pytest.mark.django_db
def test_snapshot_create_then_list(seeded):
    client = Client()
    # Use a fake POST without CSRF via enforce_csrf_checks=False (default on Client).
    resp = client.post("/wealth/snapshots/new")
    assert resp.status_code == 302
    resp = client.get("/wealth/snapshots")
    assert b"1 snapshot" in resp.content
    assert b"INR" in resp.content


@pytest.mark.django_db
def test_allocation_empty_state(db):
    # AutoLoginSelfMiddleware logs in the 'self' user.
    user = User.objects.create(username="self", base_currency="INR")
    Profile.objects.create(user=user, name="Self", is_default=True)
    response = Client().get("/wealth/allocation")
    assert response.status_code == 200
    assert b"No assets yet" in response.content


@pytest.mark.django_db
def test_snapshot_window_invalid_defaults_to_6m(seeded):
    response = Client().get("/wealth/snapshots?window=garbage")
    assert response.status_code == 200

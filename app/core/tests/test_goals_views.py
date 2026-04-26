from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import Client

from core.models import Asset, AssetCategory, EssentialsState, Goal, Profile, User


@pytest.fixture
def seeded(db):
    user = User.objects.create(username="self", base_currency="INR")
    profile = Profile.objects.create(user=user, name="Self", is_default=True)
    return profile


@pytest.mark.django_db
def test_essentials_view_renders(seeded):
    response = Client().get("/essentials/")
    assert response.status_code == 200
    assert b"Essentials" in response.content
    assert b"Emergency Fund" in response.content
    assert b"Savings Rate" in response.content


@pytest.mark.django_db
def test_essentials_update_saves(seeded):
    client = Client()
    response = client.post(
        "/essentials/update",
        {
            "emergency_fund_target_months": "9",
            "term_cover_target_multiplier": "12",
            "term_cover_amount": "5000000",
            "health_cover_amount": "500000",
            "health_cover_target": "1000000",
        },
    )
    assert response.status_code == 302
    state = EssentialsState.objects.get(profile=seeded)
    assert state.emergency_fund_target_months == 9
    assert state.term_cover_target_multiplier == 12


@pytest.mark.django_db
def test_essentials_update_invalid_shows_error(seeded):
    client = Client()
    resp = client.post(
        "/essentials/update",
        {
            "emergency_fund_target_months": "notanint",
        },
    )
    # Form invalid -> still redirects (PRG pattern, error via messages)
    assert resp.status_code == 302


@pytest.mark.django_db
def test_goal_list_empty_state(seeded):
    response = Client().get("/goals/")
    assert response.status_code == 200
    assert b"No goals yet" in response.content


@pytest.mark.django_db
def test_goal_new_get_and_post(seeded):
    client = Client()
    # GET form
    resp = client.get("/goals/new")
    assert resp.status_code == 200
    assert b"New goal" in resp.content

    # POST new goal
    resp = client.post(
        "/goals/new",
        {
            "name": "Retirement",
            "template_id": "RETIREMENT",
            "target_amount": "10000000",
            "currency": "INR",
            "target_date": "2045-12-31",
            "linked_asset_class": "NET_WORTH",
            "linked_asset_ids_raw": "",
        },
    )
    assert resp.status_code == 302
    assert Goal.objects.filter(profile=seeded, name="Retirement").exists()


@pytest.mark.django_db
def test_goal_edit_updates(seeded):
    goal = Goal.objects.create(
        profile=seeded,
        name="Old",
        target_amount=Decimal("1000"),
        currency="INR",
        target_date=date.today() + timedelta(days=365),
        linked_asset_class="NET_WORTH",
    )
    client = Client()
    resp = client.get(f"/goals/{goal.id}/edit")
    assert resp.status_code == 200

    resp = client.post(
        f"/goals/{goal.id}/edit",
        {
            "name": "New Name",
            "template_id": "",
            "target_amount": "2000",
            "currency": "INR",
            "target_date": goal.target_date.isoformat(),
            "linked_asset_class": "NET_WORTH",
            "linked_asset_ids_raw": "",
        },
    )
    assert resp.status_code == 302
    goal.refresh_from_db()
    assert goal.name == "New Name"
    assert goal.target_amount == Decimal("2000")


@pytest.mark.django_db
def test_goal_delete(seeded):
    goal = Goal.objects.create(
        profile=seeded,
        name="X",
        target_amount=Decimal("1000"),
        currency="INR",
        target_date=date.today() + timedelta(days=365),
        linked_asset_class="NET_WORTH",
    )
    resp = Client().post(f"/goals/{goal.id}/delete")
    assert resp.status_code == 302
    assert not Goal.objects.filter(id=goal.id).exists()


@pytest.mark.django_db
def test_goal_list_populated_renders_progress(seeded):
    Asset.objects.create(
        profile=seeded,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="SB",
        currency="INR",
        current_value=Decimal("50000"),
    )
    Goal.objects.create(
        profile=seeded,
        name="EF",
        target_amount=Decimal("100000"),
        currency="INR",
        target_date=date.today() + timedelta(days=365),
        linked_asset_class=AssetCategory.CASH,
    )
    resp = Client().get("/goals/")
    assert resp.status_code == 200
    assert b"EF" in resp.content


@pytest.mark.django_db
def test_inflation_calculator_get_no_params(seeded):
    resp = Client().get("/goals/inflation")
    assert resp.status_code == 200
    assert b"Inflation Calculator" in resp.content


@pytest.mark.django_db
def test_inflation_calculator_with_params(seeded):
    resp = Client().get("/goals/inflation?amount=100&years=10&inflation=6")
    assert resp.status_code == 200
    # (1.06)^10 ≈ 179.08, rounded to 179
    assert b"179" in resp.content


@pytest.mark.django_db
def test_inflation_calculator_invalid_params(seeded):
    resp = Client().get("/goals/inflation?amount=bad&years=bad")
    assert resp.status_code == 200

from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.models import (
    Asset,
    AssetCategory,
    Category,
    EssentialsState,
    Profile,
    Transaction,
    TxType,
    User,
)
from core.services.allocation import compute_allocation
from core.services.insights import rule_based_insights
from core.services.networth import compute_net_worth


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    profile = Profile.objects.create(user=user, name="Self", is_default=True)
    EssentialsState.objects.create(
        profile=profile, emergency_fund_target_months=6, health_cover_target=Decimal("1000000")
    )
    return profile


def _tx(profile, cat, amount, when, ttype=TxType.EXPENSE):
    Transaction.objects.create(
        profile=profile,
        type=ttype,
        date=when,
        category=cat,
        description="t",
        amount=Decimal(str(amount)),
        currency="INR",
    )


@pytest.mark.django_db
def test_spend_change_detected(profile):
    cat = Category.objects.create(type=TxType.EXPENSE, name="Food", is_exempt=False)
    today = date.today()
    first_of_this = today.replace(day=1)
    # This month spend: 1300
    _tx(profile, cat, 1300, first_of_this)
    # Last month spend: 1000 -> 30% increase
    last_month_end = first_of_this - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    _tx(profile, cat, 1000, last_month_start)

    nw = compute_net_worth(profile)
    alloc = compute_allocation(profile)
    insights = rule_based_insights(profile, net_worth=nw, allocation=alloc)
    texts = " ".join(i.text for i in insights)
    assert "Food" in texts


@pytest.mark.django_db
def test_emergency_fund_short(profile):
    # Cash asset of 5000, monthly expense of 5000 -> covers 1 month < 6
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="SB",
        currency="INR",
        current_value=Decimal("5000"),
    )
    cat = Category.objects.create(type=TxType.EXPENSE, name="Rent", is_exempt=False)
    first_of_this = date.today().replace(day=1)
    last_month_end = first_of_this - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    _tx(profile, cat, 5000, last_month_start)

    nw = compute_net_worth(profile)
    alloc = compute_allocation(profile)
    insights = rule_based_insights(profile, net_worth=nw, allocation=alloc)
    texts = " ".join(i.text for i in insights)
    assert "Emergency fund" in texts


@pytest.mark.django_db
def test_term_cover_cta_when_missing(profile):
    nw = compute_net_worth(profile)
    alloc = compute_allocation(profile)
    insights = rule_based_insights(profile, net_worth=nw, allocation=alloc)
    kinds_and_text = [(i.kind, i.text) for i in insights]
    assert any(kind == "cta" and "term-insurance" in text for kind, text in kinds_and_text)


@pytest.mark.django_db
def test_no_insights_when_nothing_notable(db):
    user = User.objects.create(username="u", base_currency="INR")
    prof = Profile.objects.create(user=user, name="Clean", is_default=False)
    # No EssentialsState, no assets, no txs => no insights
    nw = compute_net_worth(prof)
    alloc = compute_allocation(prof)
    assert rule_based_insights(prof, net_worth=nw, allocation=alloc) == []

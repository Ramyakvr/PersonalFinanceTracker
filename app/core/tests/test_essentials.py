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
from core.services.essentials import compute_essentials, update_essentials


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


def _mk_expense(profile, amount, d, exempt=False):
    cat = Category.objects.create(
        profile=profile, type=TxType.EXPENSE, name=f"Exp{d}-{amount}", is_exempt=exempt
    )
    return Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=d,
        category=cat,
        description="x",
        amount=Decimal(amount),
        currency="INR",
    )


def _mk_income(profile, amount, d):
    cat, _ = Category.objects.get_or_create(
        profile=profile, type=TxType.INCOME, name="Salary", defaults={"is_exempt": False}
    )
    return Transaction.objects.create(
        profile=profile,
        type=TxType.INCOME,
        date=d,
        category=cat,
        description="sal",
        amount=Decimal(amount),
        currency="INR",
    )


@pytest.mark.django_db
def test_compute_essentials_empty_profile(profile):
    report = compute_essentials(profile)
    assert len(report.cards) == 4
    keys = {c.key for c in report.cards}
    assert keys == {"emergency_fund", "savings_rate", "term_insurance", "health_insurance"}
    # Empty profile: every score is 0
    assert report.overall_score == Decimal("0")


@pytest.mark.django_db
def test_emergency_fund_card_maxes_out(profile):
    # Target = 6 months (default). Make cash big enough to be over-covered.
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="SB",
        currency="INR",
        current_value=Decimal("600000"),
    )
    # Last month + 62 days window fallback: add a this-month expense so avg_monthly_expense
    # becomes positive.
    today = date.today()
    _mk_expense(profile, "10000", today.replace(day=1))
    report = compute_essentials(profile)
    ef = next(c for c in report.cards if c.key == "emergency_fund")
    # 600000 / 10000 = 60 months; target 6 months -> 1000% clamped to 100
    assert ef.score == Decimal("100")
    assert ef.progress_pct == Decimal("100")


@pytest.mark.django_db
def test_term_insurance_card_computed_from_income(profile):
    # Annual income 1,200,000 (trailing 365 d). Multiplier 10 -> target 12M. Cover 6M -> 50%.
    EssentialsState.objects.create(
        profile=profile,
        emergency_fund_target_months=6,
        term_cover_amount=Decimal("6000000"),
        term_cover_target_multiplier=10,
    )
    _mk_income(profile, "1200000", date.today() - timedelta(days=30))
    report = compute_essentials(profile)
    term = next(c for c in report.cards if c.key == "term_insurance")
    # 6M / (1.2M × 10) = 50%
    assert term.score == Decimal("50")


@pytest.mark.django_db
def test_health_insurance_card_matches_target(profile):
    EssentialsState.objects.create(
        profile=profile,
        health_cover_amount=Decimal("500000"),
        health_cover_target=Decimal("1000000"),
    )
    report = compute_essentials(profile)
    health = next(c for c in report.cards if c.key == "health_insurance")
    assert health.score == Decimal("50")


@pytest.mark.django_db
def test_savings_rate_card_from_last_month(profile):
    # Last month: income 100k, expense 70k -> rate 30% -> progress 100%.
    today = date.today()
    last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=15)
    _mk_income(profile, "100000", last_month)
    _mk_expense(profile, "70000", last_month)
    report = compute_essentials(profile)
    sr = next(c for c in report.cards if c.key == "savings_rate")
    assert sr.score == Decimal("100")


@pytest.mark.django_db
def test_overall_score_is_average_of_cards(profile):
    # Prime health only: 50%. Others = 0. Average = 12.5.
    EssentialsState.objects.create(
        profile=profile,
        health_cover_amount=Decimal("500000"),
        health_cover_target=Decimal("1000000"),
    )
    report = compute_essentials(profile)
    assert report.overall_score == Decimal("12.5")


@pytest.mark.django_db
def test_update_essentials_upserts(profile):
    state = update_essentials(profile, emergency_fund_target_months=9)
    assert state.emergency_fund_target_months == 9
    # Round-trip: upsert again mutates the same row.
    state2 = update_essentials(profile, term_cover_amount=Decimal("5000000"))
    assert state2.id == state.id
    assert state2.emergency_fund_target_months == 9
    assert state2.term_cover_amount == Decimal("5000000")


@pytest.mark.django_db
def test_update_essentials_skips_none_values(profile):
    # Prime a value, then pass None and confirm it doesn't clobber.
    update_essentials(profile, term_cover_amount=Decimal("1000000"))
    state = update_essentials(profile, term_cover_amount=None, emergency_fund_target_months=3)
    assert state.term_cover_amount == Decimal("1000000")
    assert state.emergency_fund_target_months == 3

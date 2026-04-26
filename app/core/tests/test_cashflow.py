from datetime import date
from decimal import Decimal

import pytest

from core.models import Category, Profile, Transaction, TxType, User
from core.services.cashflow import cashflow


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.mark.django_db
def test_cashflow_sums_income_and_expense(profile):
    cat_in = Category.objects.create(type=TxType.INCOME, name="Salary")
    cat_out = Category.objects.create(type=TxType.EXPENSE, name="Rent")
    Transaction.objects.create(
        profile=profile,
        type=TxType.INCOME,
        date=date(2026, 3, 1),
        category=cat_in,
        description="Mar salary",
        amount=Decimal("100000"),
        currency="INR",
    )
    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 3, 5),
        category=cat_out,
        description="rent",
        amount=Decimal("35000"),
        currency="INR",
    )
    cf = cashflow(profile, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))
    assert cf.income == Decimal("100000")
    assert cf.expense == Decimal("35000")
    assert cf.net == Decimal("65000")


@pytest.mark.django_db
def test_cashflow_skips_exempt_and_other_ccy(profile):
    cat_exempt = Category.objects.create(type=TxType.EXPENSE, name="Investment", is_exempt=True)
    cat_out = Category.objects.create(type=TxType.EXPENSE, name="Food")
    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 3, 1),
        category=cat_exempt,
        description="SIP",
        amount=Decimal("10000"),
        currency="INR",
    )
    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 3, 5),
        category=cat_out,
        description="dinner",
        amount=Decimal("2000"),
        currency="INR",
    )
    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 3, 5),
        category=cat_out,
        description="usd",
        amount=Decimal("500"),
        currency="USD",
    )
    cf = cashflow(profile, date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))
    assert cf.expense == Decimal("2000")  # exempt + USD both skipped

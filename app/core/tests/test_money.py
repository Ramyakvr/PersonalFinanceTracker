from decimal import Decimal

import pytest

from core.models import FxRate, User
from core.money import FxRateMissingError, format_money, to_base_currency


@pytest.fixture
def user(db):
    return User.objects.create(username="self", base_currency="INR")


@pytest.mark.django_db
def test_same_currency_passthrough(user):
    assert to_base_currency(Decimal("1500.00"), "INR", "INR", user=user) == Decimal("1500.00")


@pytest.mark.django_db
def test_cross_currency_uses_stored_rate(user):
    FxRate.objects.create(user=user, from_ccy="USD", to_ccy="INR", rate=Decimal("83.0"))
    assert to_base_currency(Decimal("100"), "USD", "INR", user=user) == Decimal("8300.0")


@pytest.mark.django_db
def test_rate_refresh_overwrites(user):
    fx = FxRate.objects.create(user=user, from_ccy="USD", to_ccy="INR", rate=Decimal("80.0"))
    fx.rate = Decimal("85.0")
    fx.save()
    assert to_base_currency(Decimal("100"), "USD", "INR", user=user) == Decimal("8500.0")


@pytest.mark.django_db
def test_missing_rate_raises(user):
    with pytest.raises(FxRateMissingError):
        to_base_currency(Decimal("100"), "JPY", "INR", user=user)


def test_float_input_rejected():
    with pytest.raises(TypeError):
        to_base_currency(100.0, "INR", "INR", user=None)  # type: ignore[arg-type]


def test_format_money_inr():
    assert format_money(Decimal("1234567.89"), "INR") == "\u20b91,234,567.89"


def test_format_money_unknown_ccy_uses_code():
    assert format_money(Decimal("42"), "JPY").startswith("JPY ")

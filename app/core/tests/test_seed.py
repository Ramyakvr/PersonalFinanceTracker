import pytest
from django.core.management import call_command

from core.models import (
    AllocationTarget,
    Category,
    EssentialsState,
    FxRate,
    Profile,
    TxType,
    User,
)


@pytest.mark.django_db
def test_seed_creates_expected_rows():
    call_command("seed")

    user = User.objects.get(username="self")
    assert user.base_currency == "INR"

    profile = Profile.objects.get(user=user, name="Self")
    assert profile.is_default is True

    assert FxRate.objects.filter(user=user, from_ccy="USD", to_ccy="INR").exists()

    assert Category.objects.filter(profile=profile, type=TxType.EXPENSE).count() == 21
    assert Category.objects.filter(profile=profile, type=TxType.INCOME).count() == 10
    assert (
        Category.objects.filter(profile=profile, name="Investment", type=TxType.EXPENSE)
        .get()
        .is_exempt
        is True
    )
    assert (
        Category.objects.filter(profile=profile, name="Credit Card Payment", type=TxType.EXPENSE)
        .get()
        .is_exempt
        is True
    )

    target = AllocationTarget.objects.get(profile=profile, preset_name="Default")
    assert target.percent_by_class["EQUITY"] == 55
    assert sum(target.percent_by_class.values()) == 100

    essentials = EssentialsState.objects.get(profile=profile)
    assert essentials.emergency_fund_target_months == 6
    assert essentials.term_cover_target_multiplier == 10


@pytest.mark.django_db
def test_seed_is_idempotent():
    call_command("seed")
    call_command("seed")

    profile = Profile.objects.get(name="Self")
    assert Category.objects.filter(profile=profile, type=TxType.EXPENSE).count() == 21
    assert Category.objects.filter(profile=profile, type=TxType.INCOME).count() == 10
    assert AllocationTarget.objects.filter(profile=profile).count() == 1
    assert EssentialsState.objects.filter(profile=profile).count() == 1

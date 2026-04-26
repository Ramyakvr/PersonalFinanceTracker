from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError

from core.models import (
    Asset,
    AssetCategory,
    Category,
    Liability,
    LiabilityCategory,
    Profile,
    Tag,
    Transaction,
    TxType,
    User,
)


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.mark.django_db
def test_tag_unique_per_profile(profile):
    Tag.objects.create(profile=profile, label="tax-saving")
    with pytest.raises(IntegrityError):
        Tag.objects.create(profile=profile, label="tax-saving")


@pytest.mark.django_db
def test_category_unique_per_profile_type_name(profile):
    Category.objects.create(profile=profile, type=TxType.EXPENSE, name="Food")
    with pytest.raises(IntegrityError):
        Category.objects.create(profile=profile, type=TxType.EXPENSE, name="Food")


@pytest.mark.django_db
def test_category_same_name_different_type_allowed(profile):
    Category.objects.create(profile=profile, type=TxType.EXPENSE, name="Other")
    # Same name under INCOME is a different row — allowed.
    Category.objects.create(profile=profile, type=TxType.INCOME, name="Other")


@pytest.mark.django_db
def test_transaction_category_protect_on_delete(profile):
    cat = Category.objects.create(profile=profile, type=TxType.EXPENSE, name="Rent")
    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 4, 1),
        category=cat,
        description="April rent",
        amount=Decimal("30000.00"),
    )
    # Category should be protected — deleting it while referenced raises.
    with pytest.raises(IntegrityError):
        cat.delete()


@pytest.mark.django_db
def test_profile_cascade_deletes_children(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        current_value=Decimal("150000.00"),
    )
    Liability.objects.create(
        profile=profile,
        category=LiabilityCategory.HOME_LOAN,
        name="Home Loan",
        outstanding_amount=Decimal("4500000.00"),
    )
    profile.delete()
    assert Asset.objects.count() == 0
    assert Liability.objects.count() == 0


@pytest.mark.django_db
def test_asset_tag_m2m(profile):
    tag = Tag.objects.create(profile=profile, label="tax-saving")
    asset = Asset.objects.create(
        profile=profile,
        category=AssetCategory.RETIREMENT,
        subtype="PPF",
        name="SBI PPF",
        current_value=Decimal("500000.00"),
    )
    asset.tags.add(tag)
    assert list(tag.assets.all()) == [asset]

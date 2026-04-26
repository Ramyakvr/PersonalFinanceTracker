import csv
import io
import json
from datetime import date
from decimal import Decimal

import pytest

from core.models import (
    AllocationTarget,
    Asset,
    AssetCategory,
    Category,
    EssentialsState,
    Goal,
    Liability,
    LiabilityCategory,
    Profile,
    Transaction,
    TxType,
    User,
)
from core.services import exports as exp


@pytest.fixture
def seeded(db):
    user = User.objects.create(username="self", base_currency="INR", first_name="R")
    profile = Profile.objects.create(user=user, name="Self", is_default=True)
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("500000.1234"),
    )
    Liability.objects.create(
        profile=profile,
        category=LiabilityCategory.CREDIT_CARD,
        name="Card",
        currency="INR",
        outstanding_amount=Decimal("12000"),
    )
    cat = Category.objects.create(type=TxType.EXPENSE, name="Food")
    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 3, 5),
        category=cat,
        description="Dinner",
        amount=Decimal("1200"),
        currency="INR",
    )
    Goal.objects.create(
        profile=profile,
        name="EF",
        target_amount=Decimal("100000"),
        currency="INR",
        target_date=date(2027, 1, 1),
        linked_asset_class="CASH",
    )
    AllocationTarget.objects.create(
        profile=profile,
        preset_name="Default",
        percent_by_class={"EQUITY": 60, "BONDS_DEBT": 40},
    )
    EssentialsState.objects.create(profile=profile, emergency_fund_target_months=6)
    return profile


@pytest.mark.django_db
def test_export_all_is_valid_json_and_has_every_section(seeded):
    data = exp.export_all(seeded)
    # Ensure all expected sections exist.
    for key in [
        "schema_version",
        "exported_at",
        "user",
        "profile",
        "assets",
        "liabilities",
        "transactions",
        "categories",
        "goals",
        "snapshots",
        "allocation_targets",
        "essentials",
    ]:
        assert key in data
    # Must serialize cleanly (Decimals preserved as strings).
    payload = json.dumps(data)
    roundtrip = json.loads(payload)
    assert roundtrip["assets"][0]["current_value"] == "500000.1234"
    assert roundtrip["transactions"][0]["category"] == "Food"
    assert roundtrip["essentials"]["emergency_fund_target_months"] == 6


@pytest.mark.django_db
def test_export_csv_assets(seeded):
    raw = exp.export_csv(seeded, "assets")
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["name"] == "INFY"
    assert rows[0]["category"] == "EQUITY"


@pytest.mark.django_db
def test_export_csv_transactions_includes_category_name(seeded):
    raw = exp.export_csv(seeded, "transactions")
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)
    assert rows[0]["category"] == "Food"
    assert rows[0]["amount"] == "1200.0000"


@pytest.mark.django_db
def test_export_csv_unknown_table_raises(seeded):
    with pytest.raises(ValueError):
        exp.export_csv(seeded, "mystery")


@pytest.mark.django_db
def test_wipe_data_preserves_user_and_system_categories(seeded):
    # Add a custom profile-scoped category too.
    Category.objects.create(profile=seeded, type=TxType.EXPENSE, name="Custom", is_custom=True)
    counts = exp.wipe_data(seeded)
    assert counts["assets"] == 1
    assert counts["liabilities"] == 1
    assert counts["transactions"] == 1
    assert counts["goals"] == 1
    # After wipe, user still exists and system categories remain.
    assert User.objects.filter(username="self").exists()
    assert Profile.objects.filter(id=seeded.id).exists()
    assert Category.objects.filter(profile=None, name="Food").exists()  # system cat survives
    assert Asset.objects.filter(profile=seeded).count() == 0
    assert Transaction.objects.filter(profile=seeded).count() == 0

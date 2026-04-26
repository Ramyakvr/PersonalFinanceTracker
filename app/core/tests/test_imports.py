from decimal import Decimal

import pytest

from core.models import (
    Asset,
    AssetCategory,
    Category,
    ImportStatus,
    Profile,
    Transaction,
    TxType,
    User,
)
from core.services import imports as imp


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_assets_append_happy_path(profile):
    csv = (
        "name,category,subtype,currency,current_value,cost_basis\n"
        "INFY,EQUITY,DIRECT_STOCK,INR,500000,300000\n"
        "TCS,EQUITY,DIRECT_STOCK,INR,250000,\n"
    )
    result = imp.import_assets(profile, csv)
    assert result.ok
    assert result.inserted == 2
    assert result.updated == 0
    assert Asset.objects.filter(profile=profile).count() == 2
    assert result.job.status == ImportStatus.OK
    assert result.job.rows_imported == 2


@pytest.mark.django_db
def test_import_assets_update_by_name(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value=Decimal("100000"),
    )
    csv = "name,category,subtype,currency,current_value\nINFY,EQUITY,DIRECT_STOCK,INR,999999\n"
    result = imp.import_assets(profile, csv, mode=imp.MODE_UPDATE)
    assert result.updated == 1
    assert result.inserted == 0
    asset = Asset.objects.get(profile=profile, name="INFY")
    assert asset.current_value == Decimal("999999")


@pytest.mark.django_db
def test_import_assets_update_by_name_inserts_when_not_found(profile):
    csv = "name,category,subtype,currency,current_value\nZZZ,EQUITY,DIRECT_STOCK,INR,100\n"
    result = imp.import_assets(profile, csv, mode=imp.MODE_UPDATE)
    assert result.inserted == 1
    assert result.updated == 0


@pytest.mark.django_db
def test_import_assets_rejects_unknown_category(profile):
    csv = "name,category,subtype,currency,current_value\nX,BITS,DIRECT_STOCK,INR,100\n"
    result = imp.import_assets(profile, csv)
    assert result.skipped == 1
    assert result.inserted == 0
    assert any("unknown category" in e for e in result.errors)


@pytest.mark.django_db
def test_import_assets_skips_missing_required(profile):
    csv = "name,category,subtype,currency,current_value\n,EQUITY,DIRECT_STOCK,INR,100\n"
    result = imp.import_assets(profile, csv)
    assert result.skipped == 1
    assert any("missing name" in e for e in result.errors)


@pytest.mark.django_db
def test_import_assets_invalid_current_value_is_skipped(profile):
    csv = "name,category,subtype,currency,current_value\nBad,EQUITY,DIRECT_STOCK,INR,notanumber\n"
    result = imp.import_assets(profile, csv)
    assert result.skipped == 1
    assert any("current_value" in e for e in result.errors)


@pytest.mark.django_db
def test_import_assets_bad_mode_raises(profile):
    with pytest.raises(ValueError):
        imp.import_assets(profile, "name,category\n", mode="mystery")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_transactions_append_happy_path(profile):
    Category.objects.create(type=TxType.EXPENSE, name="Food")
    Category.objects.create(type=TxType.INCOME, name="Salary")
    csv = (
        "date,type,category,description,amount,currency,notes\n"
        "2026-03-01,INCOME,Salary,Mar salary,100000,INR,\n"
        "2026-03-05,EXPENSE,Food,Dinner,1200,INR,with team\n"
    )
    result = imp.import_transactions(profile, csv)
    assert result.ok
    assert result.inserted == 2
    assert Transaction.objects.filter(profile=profile).count() == 2


@pytest.mark.django_db
def test_import_transactions_update_by_name(profile):
    cat = Category.objects.create(type=TxType.EXPENSE, name="Food")
    from datetime import date

    Transaction.objects.create(
        profile=profile,
        type=TxType.EXPENSE,
        date=date(2026, 3, 5),
        category=cat,
        description="Dinner",
        amount=Decimal("500"),
        currency="INR",
    )
    csv = (
        "date,type,category,description,amount,currency\n2026-03-05,EXPENSE,Food,Dinner,1200,INR\n"
    )
    result = imp.import_transactions(profile, csv, mode=imp.MODE_UPDATE)
    assert result.updated == 1
    tx = Transaction.objects.get(profile=profile)
    assert tx.amount == Decimal("1200")


@pytest.mark.django_db
def test_import_transactions_unknown_category_skipped(profile):
    csv = "date,type,category,description,amount,currency\n2026-03-01,EXPENSE,Nonsense,x,100,INR\n"
    result = imp.import_transactions(profile, csv)
    assert result.skipped == 1
    assert any("unknown category" in e for e in result.errors)


@pytest.mark.django_db
def test_import_transactions_bad_date_skipped(profile):
    Category.objects.create(type=TxType.EXPENSE, name="Food")
    csv = "date,type,category,description,amount,currency\nBadDate,EXPENSE,Food,x,100,INR\n"
    result = imp.import_transactions(profile, csv)
    assert result.skipped == 1
    assert any("Unrecognized date" in e for e in result.errors)


@pytest.mark.django_db
def test_import_transactions_accepts_alternate_date_format(profile):
    Category.objects.create(type=TxType.EXPENSE, name="Food")
    csv = "date,type,category,description,amount,currency\n05/03/2026,EXPENSE,Food,x,100,INR\n"
    result = imp.import_transactions(profile, csv)
    assert result.inserted == 1


@pytest.mark.django_db
def test_import_transactions_empty_csv_errors(profile):
    result = imp.import_transactions(profile, "date,type,category,description,amount,currency\n")
    # No rows + no insertions -> status OK (empty CSV is fine) but inserted 0.
    assert result.inserted == 0


@pytest.mark.django_db
def test_list_import_jobs_ordering(profile):
    imp.import_assets(profile, "name,category,subtype,currency,current_value\n")
    imp.import_assets(profile, "name,category,subtype,currency,current_value\n")
    jobs = list(imp.list_import_jobs(profile))
    assert len(jobs) == 2
    assert jobs[0].created_at >= jobs[1].created_at

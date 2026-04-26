from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Asset, AssetCategory, Profile, Snapshot, SnapshotSource, User
from core.services.snapshots import (
    auto_snapshot_all,
    list_snapshots,
    snapshot_series,
    take_snapshot,
)


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.mark.django_db
def test_take_snapshot_freezes_values(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="A",
        currency="INR",
        current_value=Decimal("1000"),
    )
    snap = take_snapshot(profile)
    assert snap.net_worth == Decimal("1000")
    assert snap.total_assets == Decimal("1000")
    assert snap.source == SnapshotSource.MANUAL
    assert snap.base_currency == "INR"
    assert "by_asset_category" in snap.breakdown_json
    assert Decimal(snap.breakdown_json["by_asset_category"]["EQUITY"]) == Decimal("1000")


@pytest.mark.django_db
def test_snapshot_is_immutable_after_asset_change(profile):
    a = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="A",
        currency="INR",
        current_value=Decimal("1000"),
    )
    snap = take_snapshot(profile)
    a.current_value = Decimal("9999")
    a.save()
    snap.refresh_from_db()
    assert snap.net_worth == Decimal("1000")
    assert Decimal(snap.breakdown_json["by_asset_category"]["EQUITY"]) == Decimal("1000")


@pytest.mark.django_db
def test_list_snapshots_newest_first(profile):
    s1 = take_snapshot(profile)
    s2 = take_snapshot(profile)
    result = list(list_snapshots(profile))
    assert result[0].id == s2.id
    assert result[1].id == s1.id


@pytest.mark.django_db
def test_snapshot_series_window(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="SAVINGS",
        name="A",
        currency="INR",
        current_value=Decimal("100"),
    )
    s = take_snapshot(profile)
    # Force an old timestamp outside the 1m window.
    Snapshot.objects.filter(id=s.id).update(taken_at=timezone.now() - timedelta(days=40))
    recent = take_snapshot(profile)

    series_1m = snapshot_series(profile, window="1m")
    assert len(series_1m) == 1
    assert series_1m[0]["net_worth"] == str(recent.net_worth)

    series_all = snapshot_series(profile, window="all")
    assert len(series_all) == 2


@pytest.mark.django_db
def test_auto_snapshot_skips_when_recent(profile):
    take_snapshot(profile, source=SnapshotSource.MANUAL)
    result = auto_snapshot_all()
    assert result == {"created": 0, "skipped": 1}


@pytest.mark.django_db
def test_auto_snapshot_creates_when_stale(profile):
    s = take_snapshot(profile)
    Snapshot.objects.filter(id=s.id).update(taken_at=timezone.now() - timedelta(days=2))
    result = auto_snapshot_all()
    assert result["created"] == 1
    latest = list_snapshots(profile).first()
    assert latest.source == SnapshotSource.AUTO

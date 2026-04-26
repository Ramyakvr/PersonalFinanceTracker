"""Tests for migration ``0005_backfill_asset_instrument``.

The migration's ``forward`` callable is importable and pure-data, so we
invoke it directly against real rows rather than using the slower
``MigrationExecutor`` harness. The behaviour under test:

* Existing Assets with equity / MF subtypes get linked to a new (or existing)
  Instrument row.
* Reruns are idempotent -- the second pass touches nothing.
* Non-tradeable assets (FD, PPF, REAL_ESTATE) are skipped.
* Multiple Assets with the same ``instrument_symbol`` de-dup to one
  Instrument row.
* New Instruments land with ``needs_review=True`` so the UI can prompt
  for ISIN confirmation.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from django.apps import apps as django_apps

from core.models import (
    Asset,
    AssetCategory,
    Instrument,
    Profile,
    User,
)


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


def _forward():
    """Invoke migration 0005's ``forward`` callable against the live DB.

    Migration module names start with a digit so they aren't importable via
    dotted path -- we load the file explicitly.
    """

    path = (
        Path(__file__).parent.parent
        / "migrations"
        / "0005_backfill_asset_instrument.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.forward(django_apps, schema_editor=None)


@pytest.mark.django_db
def test_direct_stock_gets_linked_to_new_instrument(profile):
    a = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("1000"),
        instrument_symbol="HDFCBANK",
    )

    _forward()
    a.refresh_from_db()
    assert a.instrument is not None
    assert a.instrument.kind == "STOCK"
    assert a.instrument.exchange_symbol == "HDFCBANK"
    assert a.instrument.needs_review is True
    assert a.instrument.isin == ""  # placeholder pending user confirmation


@pytest.mark.django_db
def test_equity_mf_gets_mf_kind(profile):
    a = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="EQUITY_MF",
        name="Parag Parikh Flexi Cap",
        currency="INR",
        current_value=Decimal("2500"),
        instrument_symbol="",
    )
    _forward()
    a.refresh_from_db()
    assert a.instrument is not None
    assert a.instrument.kind == "MF"


@pytest.mark.django_db
def test_fixed_deposit_is_not_linked(profile):
    a = Asset.objects.create(
        profile=profile,
        category=AssetCategory.CASH,
        subtype="FD",
        name="HDFC FD",
        currency="INR",
        current_value=Decimal("50000"),
    )
    _forward()
    a.refresh_from_db()
    assert a.instrument is None


@pytest.mark.django_db
def test_multiple_assets_same_symbol_dedupe(profile):
    a1 = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("1000"),
        instrument_symbol="HDFCBANK",
    )
    a2 = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank (second)",
        currency="INR",
        current_value=Decimal("500"),
        instrument_symbol="HDFCBANK",
    )

    _forward()
    a1.refresh_from_db()
    a2.refresh_from_db()
    assert a1.instrument is not None
    assert a1.instrument_id == a2.instrument_id
    assert Instrument.objects.filter(profile=profile, exchange_symbol="HDFCBANK").count() == 1


@pytest.mark.django_db
def test_reuses_existing_instrument(profile):
    """If an Instrument for this symbol was already created (e.g. by a prior
    Zerodha import), the backfill links to it instead of creating a new one."""

    existing = Instrument.objects.create(
        profile=profile,
        isin="INE040A01034",
        exchange_symbol="HDFCBANK",
        name="HDFC Bank",
        kind="STOCK",
        needs_review=False,
    )
    a = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("1000"),
        instrument_symbol="HDFCBANK",
    )
    _forward()
    a.refresh_from_db()
    assert a.instrument_id == existing.id
    existing.refresh_from_db()
    assert existing.needs_review is False  # unchanged by backfill


@pytest.mark.django_db
def test_already_linked_asset_is_untouched(profile):
    instr = Instrument.objects.create(
        profile=profile,
        isin="INE040A01034",
        exchange_symbol="HDFCBANK",
        name="HDFC Bank",
        kind="STOCK",
    )
    a = Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("1000"),
        instrument_symbol="HDFCBANK",
        instrument=instr,
    )
    _forward()
    a.refresh_from_db()
    assert a.instrument_id == instr.id


@pytest.mark.django_db
def test_forward_is_idempotent(profile):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("1000"),
        instrument_symbol="HDFCBANK",
    )
    _forward()
    count_after_first = Instrument.objects.filter(profile=profile).count()
    _forward()
    count_after_second = Instrument.objects.filter(profile=profile).count()
    assert count_after_first == count_after_second

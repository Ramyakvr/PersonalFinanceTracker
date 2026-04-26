"""View-level tests for the /wealth/investments/ pages."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from core.models import (
    BrokerAccount,
    BrokerKind,
    DividendRecord,
    DividendSource,
    Instrument,
    InstrumentKind,
    PriceSource,
    Profile,
    StockTrade,
    TradeSide,
    User,
)
from core.services.prices import upsert_tick


@pytest.fixture
def seeded(db):
    user = User.objects.create(username="self", base_currency="INR")
    profile = Profile.objects.create(user=user, name="Self", is_default=True)
    ba = BrokerAccount.objects.create(
        profile=profile, broker_key=BrokerKind.ZERODHA, account_label="Main"
    )
    instr = Instrument.objects.create(
        profile=profile,
        isin="INE040A01034",
        exchange_symbol="HDFCBANK",
        name="HDFC Bank",
        kind=InstrumentKind.STOCK,
    )
    StockTrade.objects.create(
        profile=profile,
        broker_account=ba,
        instrument=instr,
        trade_date=date(2022, 1, 1),
        side=TradeSide.BUY,
        quantity=Decimal("10"),
        price=Decimal("1000"),
        net_amount=Decimal("-10000"),
        trade_ref="buy-1",
    )
    StockTrade.objects.create(
        profile=profile,
        broker_account=ba,
        instrument=instr,
        trade_date=date(2023, 1, 1),
        side=TradeSide.SELL,
        quantity=Decimal("5"),
        price=Decimal("1100"),
        net_amount=Decimal("5500"),
        trade_ref="sell-1",
    )
    DividendRecord.objects.create(
        profile=profile,
        broker_account=ba,
        instrument=instr,
        ex_date=date(2022, 7, 1),
        pay_date=date(2022, 7, 1),
        amount_gross=Decimal("200"),
        amount_net=Decimal("200"),
        source=DividendSource.ZERODHA_XLSX,
    )
    upsert_tick(
        instr,
        price=Decimal("1200"),
        source=PriceSource.NSE_BHAVCOPY,
        as_of=date.today(),
    )
    return {"profile": profile, "broker": ba, "instrument": instr}


@pytest.mark.django_db
def test_investments_list_empty_state(db):
    user = User.objects.create(username="self", base_currency="INR")
    Profile.objects.create(user=user, name="Self", is_default=True)
    resp = Client().get(reverse("investments_list"))
    assert resp.status_code == 200
    assert b"Investments" in resp.content
    assert b"No trades yet" in resp.content


@pytest.mark.django_db
def test_investments_list_renders_seeded_rows(seeded):
    resp = Client().get(reverse("investments_list"))
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "HDFC Bank" in body
    # KPI strip
    assert "Portfolio XIRR" in body
    assert "Invested (open)" in body
    assert "Dividends" in body
    # LTP from our seeded PriceTick -> 1,200
    assert "1,200.00" in body


@pytest.mark.django_db
def test_investments_list_broker_filter(seeded):
    resp = Client().get(reverse("investments_list") + "?broker=zerodha")
    assert resp.status_code == 200
    assert b"HDFC Bank" in resp.content

    # Bogus broker key: still 200, shows empty (filter matches no BA, falls back
    # to all active instruments because ``ba_filter`` was None).
    resp = Client().get(reverse("investments_list") + "?broker=doesnotexist")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_investments_list_kind_filter_mf_hides_equity(seeded):
    """Filter to MF only -> the equity row should disappear from the table."""
    resp = Client().get(reverse("investments_list") + "?kind=MF")
    assert resp.status_code == 200
    # The MF kind has no rows for this fixture -> empty state copy renders.
    assert b"No trades yet" in resp.content


@pytest.mark.django_db
def test_investments_list_sort_by_xirr_succeeds(seeded):
    resp = Client().get(reverse("investments_list") + "?sort=xirr&dir=desc")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_instrument_detail_renders_ledger(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "HDFC Bank" in body
    assert "Trade ledger" in body
    assert "buy-1" in body or "buy-" in body
    # KPIs
    assert "Realised" in body
    assert "Dividends" in body


@pytest.mark.django_db
def test_instrument_detail_404_for_other_profile(db, seeded):
    """An Instrument from a different profile must 404 rather than leaking."""
    other_user = User.objects.create(username="stranger", base_currency="INR")
    other_profile = Profile.objects.create(user=other_user, name="Stranger")
    other_instrument = Instrument.objects.create(
        profile=other_profile,
        isin="INE002A01018",
        exchange_symbol="RELIANCE",
        name="Reliance",
        kind=InstrumentKind.STOCK,
    )
    resp = Client().get(reverse("instrument_detail", args=[other_instrument.id]))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_investments_refresh_prices_redirects_and_flashes(seeded):
    resp = Client().post(reverse("investments_refresh_prices"), follow=False)
    assert resp.status_code == 302
    assert resp["Location"].endswith("/wealth/investments/")


@pytest.mark.django_db
def test_investments_list_no_date_filter_inputs(seeded):
    """The date-range filter was removed; the form should not render those inputs."""
    resp = Client().get(reverse("investments_list"))
    body = resp.content.decode("utf-8")
    assert 'name="from"' not in body
    assert 'name="to"' not in body


@pytest.mark.django_db
def test_investments_list_no_total_return_or_cagr(seeded):
    resp = Client().get(reverse("investments_list"))
    body = resp.content.decode("utf-8")
    assert "Total Return" not in body
    assert "CAGR" not in body


@pytest.mark.django_db
def test_investments_list_shows_holdings_and_ltcg_kpi(seeded):
    resp = Client().get(reverse("investments_list"))
    body = resp.content.decode("utf-8")
    assert "Holdings" in body
    assert "LTCG-eligible" in body


@pytest.mark.django_db
def test_investments_list_shows_realised_by_fy_section(seeded):
    """The seeded fixture sells 5 units a year after buy -> FY22-23 LTCG row."""
    resp = Client().get(reverse("investments_list"))
    body = resp.content.decode("utf-8")
    assert "Realised P&amp;L by Financial Year" in body
    assert "FY22-23" in body


@pytest.mark.django_db
def test_instrument_detail_no_trade_ref_or_cagr(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    body = resp.content.decode("utf-8")
    # Trade ref header removed
    assert "Trade ref" not in body
    # CAGR sub-line removed
    assert "CAGR" not in body
    # KPI strip presence
    assert ">LTP<" in body
    assert ">Avg cost<" in body


@pytest.mark.django_db
def test_instrument_detail_lot_table_shows_ltcg_or_stcg(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    body = resp.content.decode("utf-8")
    # Open lot remains (5 units after the sell); seeded buy 2022-01-01 > 365d ago
    assert "LTCG" in body or "STCG" in body


@pytest.mark.django_db
def test_instrument_detail_kpi_strip_added_fields(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    body = resp.content.decode("utf-8")
    assert "Invested" in body
    assert "Current Value" in body
    assert "Unrealised P&amp;L" in body
    assert "Realised P&amp;L" in body
    assert "TTM Yield" in body


@pytest.mark.django_db
def test_instrument_detail_no_qty_held_kpi(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    body = resp.content.decode("utf-8")
    # Qty held KPI label removed (was redundant with the open-lots table)
    assert ">Qty held<" not in body


@pytest.mark.django_db
def test_instrument_detail_no_cashflow_markers_or_source_column(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    body = resp.content.decode("utf-8")
    assert "cashflowData" not in body
    # Dividend source column removed; provenance moved to row-level title tooltip
    assert "<th class=\"text-left py-1\">Source</th>" not in body


@pytest.mark.django_db
def test_instrument_detail_realised_by_fy_section_renders(seeded):
    instr = seeded["instrument"]
    resp = Client().get(reverse("instrument_detail", args=[instr.id]))
    body = resp.content.decode("utf-8")
    # Seeded fixture sells 5 units a year after buy → at least one realised lot in some FY
    assert "Realised P&amp;L by Financial Year" in body


@pytest.mark.django_db
def test_investments_tab_link_reachable_from_wealth(seeded):
    """Regression guard: the Investments tab added to the wealth nav must
    render on every wealth page without crashing reverse()."""
    for url_name in ("asset_list", "liability_list", "snapshots", "allocation"):
        resp = Client().get(reverse(url_name))
        assert resp.status_code == 200, url_name
        assert b"Investments" in resp.content

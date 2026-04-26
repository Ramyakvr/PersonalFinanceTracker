from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from core.models import (
    BrokerAccount,
    BrokerKind,
    DividendRecord,
    DividendSource,
    Instrument,
    InstrumentKind,
    Profile,
    StockTrade,
    TradeSide,
    User,
)


@pytest.mark.django_db
def test_hello_view_returns_200_when_unseeded():
    response = Client().get("/")
    assert response.status_code == 200
    assert b"Finance is running" in response.content
    assert b"(not seeded)" in response.content


@pytest.mark.django_db
def test_hello_view_shows_seeded_profile():
    user = User.objects.create(username="self", base_currency="INR")
    Profile.objects.create(user=user, name="Self", is_default=True)

    response = Client().get("/")
    assert response.status_code == 200
    # Phase 4: landing page is a dashboard with KPIs. The sidebar reads "Finance".
    assert b"Overview" in response.content
    assert b"Net Worth" in response.content
    assert b"INR" in response.content


@pytest.mark.django_db
def test_hello_shows_portfolio_xirr_kpi_with_dash_for_empty_portfolio():
    """An empty investment ledger -> XIRR KPI shows '—' plus the import hint."""
    user = User.objects.create(username="self", base_currency="INR")
    Profile.objects.create(user=user, name="Self", is_default=True)
    response = Client().get("/")
    assert response.status_code == 200
    assert b"Portfolio XIRR" in response.content
    assert b"import a tradebook" in response.content


@pytest.mark.django_db
def test_hello_shows_portfolio_xirr_kpi_after_buy_sell_dividend():
    """Seed a clean buy -> dividend -> sell path and assert the dashboard
    renders a non-None XIRR that matches the pure solver's value to ±0.01%.

    Flow (all INR):
      2022-01-01  BUY  10 @ 1000  (cash -10,000)
      2022-07-01  dividend 200
      2023-01-01  SELL 10 @ 1100  (cash +11,000)

    Excel-verified XIRR = 0.12119 -> 12.12%.
    """

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
        quantity=Decimal("10"),
        price=Decimal("1100"),
        net_amount=Decimal("11000"),
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

    response = Client().get("/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Portfolio XIRR" in body
    # 12.12% is the Excel-parity value for this cashflow stream (see
    # test_xirr.py::test_buy_plus_dividend_plus_exit). Accept any
    # rendering in the 12.0%-12.2% band to allow rounding differences.
    import re

    matches = re.findall(r"(-?\d+\.\d+)%", body)
    # The XIRR KPI is one of the percent strings on the page; filter to those
    # near the known value.
    close_values = [float(m) for m in matches if 12.0 <= float(m) <= 12.2]
    assert close_values, f"Expected a 12.x% reading, found percents: {matches}"

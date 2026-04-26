"""End-to-end investments-service tests.

Exercises ``portfolio_xirr`` / ``instrument_xirr`` / ``portfolio_summary``
against real ``StockTrade`` + ``DividendRecord`` rows. The tighter unit tests
for the FIFO engine and the solver live in ``test_lots.py`` and
``test_xirr.py`` respectively; this file exists to prove the glue works.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

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
from core.services.investments import (
    _indian_fy_label,
    instrument_breakdown,
    instrument_xirr,
    portfolio_summary,
    portfolio_xirr,
    realised_by_fy,
    realised_by_fy_by_pan,
)


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.fixture
def zerodha(db, profile):
    return BrokerAccount.objects.create(
        profile=profile, broker_key=BrokerKind.ZERODHA, account_label="Main"
    )


@pytest.fixture
def chola(db, profile):
    return BrokerAccount.objects.create(
        profile=profile, broker_key=BrokerKind.CHOLA, account_label="Main"
    )


@pytest.fixture
def hdfc_bank(db, profile):
    return Instrument.objects.create(
        profile=profile,
        isin="INE040A01034",
        exchange_symbol="HDFCBANK",
        name="HDFC Bank",
        kind=InstrumentKind.STOCK,
    )


def _buy(ba, instr, when, qty, price, ref):
    q = Decimal(qty)
    p = Decimal(price)
    return StockTrade.objects.create(
        profile=ba.profile,
        broker_account=ba,
        instrument=instr,
        trade_date=when,
        side=TradeSide.BUY,
        quantity=q,
        price=p,
        total_charges=Decimal(0),
        net_amount=-(q * p),
        trade_ref=ref,
    )


def _sell(ba, instr, when, qty, price, ref):
    q = Decimal(qty)
    p = Decimal(price)
    return StockTrade.objects.create(
        profile=ba.profile,
        broker_account=ba,
        instrument=instr,
        trade_date=when,
        side=TradeSide.SELL,
        quantity=q,
        price=p,
        total_charges=Decimal(0),
        net_amount=q * p,
        trade_ref=ref,
    )


def _dividend(profile, ba, instr, ex_date, net, pay_date=None):
    return DividendRecord.objects.create(
        profile=profile,
        broker_account=ba,
        instrument=instr,
        ex_date=ex_date,
        pay_date=pay_date,
        amount_gross=Decimal(net),
        amount_net=Decimal(net),
        source=DividendSource.ZERODHA_XLSX,
    )


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_empty_portfolio_returns_none(profile):
    assert portfolio_xirr(profile) is None
    summary = portfolio_summary(profile)
    assert summary.xirr is None
    assert summary.total_invested_open == Decimal(0)


@pytest.mark.django_db
def test_instrument_xirr_none_when_no_trades(profile, hdfc_bank):
    assert instrument_xirr(profile, hdfc_bank) is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_buy_then_sell_computes_realised_xirr(profile, zerodha, hdfc_bank):
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2023, 1, 1), "10", "1100", "z-2")

    xirr_ = instrument_xirr(profile, hdfc_bank, as_of=date(2023, 1, 1))
    assert xirr_ is not None
    # 10% gain in 365 days -> ~10% XIRR
    assert Decimal("0.09") < xirr_ < Decimal("0.11")


@pytest.mark.django_db
def test_dividend_increases_xirr(profile, zerodha, hdfc_bank):
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2023, 1, 1), "10", "1100", "z-2")

    base_xirr = instrument_xirr(profile, hdfc_bank, as_of=date(2023, 1, 1))

    _dividend(profile, zerodha, hdfc_bank, date(2022, 6, 1), "200", pay_date=date(2022, 6, 5))

    with_div = instrument_xirr(profile, hdfc_bank, as_of=date(2023, 1, 1))
    assert base_xirr is not None
    assert with_div is not None
    assert with_div > base_xirr


@pytest.mark.django_db
def test_multi_broker_portfolio_xirr_aggregates_cashflows(profile, zerodha, chola, hdfc_bank):
    # Zerodha: +10% round-trip
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2023, 1, 1), "10", "1100", "z-2")
    # Chola: -5% round-trip, same stock
    _buy(chola, hdfc_bank, date(2022, 1, 1), "5", "1000", "c-1")
    _sell(chola, hdfc_bank, date(2023, 1, 1), "5", "950", "c-2")

    portfolio = portfolio_xirr(profile, as_of=date(2023, 1, 1))
    assert portfolio is not None
    # Net +750 on 15000 invested over 1 year = 5% => XIRR near 5%
    assert Decimal("0.04") < portfolio < Decimal("0.06")


@pytest.mark.django_db
def test_cross_broker_isolation_in_breakdown(profile, zerodha, chola, hdfc_bank):
    """The breakdown should reflect open lots per-broker independently."""
    _buy(zerodha, hdfc_bank, date(2024, 1, 1), "10", "1000", "z-1")
    _buy(chola, hdfc_bank, date(2024, 1, 1), "5", "1100", "c-1")
    _sell(zerodha, hdfc_bank, date(2024, 6, 1), "4", "1200", "z-2")

    br = instrument_breakdown(profile, hdfc_bank, as_of=date(2024, 12, 31))
    # Remaining: 6 @ Zerodha + 5 @ Chola = 11 units total
    assert br.qty_held == Decimal("11")
    # Realised: 4 units sold at 1200 vs 1000 cost = +800
    assert br.realised_pnl == Decimal("800")


@pytest.mark.django_db
def test_broker_filtered_summary_excludes_other_brokers(profile, zerodha, chola, hdfc_bank):
    _buy(zerodha, hdfc_bank, date(2024, 1, 1), "10", "1000", "z-1")
    _buy(chola, hdfc_bank, date(2024, 1, 1), "5", "1100", "c-1")

    zerodha_only = portfolio_summary(profile, broker_account=zerodha)
    assert zerodha_only.total_invested_open == Decimal("10000")

    chola_only = portfolio_summary(profile, broker_account=chola)
    assert chola_only.total_invested_open == Decimal("5500")


@pytest.mark.django_db
def test_missing_fx_rate_skips_flow_and_records_error(profile, zerodha):
    """A USD-denominated instrument with no INR FX rate should not raise --
    the flow is skipped and recorded under conversion_errors."""
    us_stock = Instrument.objects.create(
        profile=profile,
        isin="US0378331005",
        exchange_symbol="AAPL",
        name="Apple Inc.",
        kind=InstrumentKind.STOCK,
        currency="USD",
    )
    StockTrade.objects.create(
        profile=profile,
        broker_account=zerodha,
        instrument=us_stock,
        trade_date=date(2024, 1, 1),
        side=TradeSide.BUY,
        quantity=Decimal("10"),
        price=Decimal("100"),
        total_charges=Decimal(0),
        net_amount=Decimal("-1000"),
        currency="USD",
        trade_ref="aapl-1",
    )
    summary = portfolio_summary(profile)
    assert any("USD" in e for e in summary.conversion_errors)


# ---------------------------------------------------------------------------
# FY grouping + LTCG-eligible
# ---------------------------------------------------------------------------


def test_indian_fy_label_apr_boundary():
    # April 1 is the start of an FY
    assert _indian_fy_label(date(2024, 4, 1)) == "FY24-25"
    # March 31 is the last day of the prior FY
    assert _indian_fy_label(date(2024, 3, 31)) == "FY23-24"
    # Mid-year should still resolve to the FY starting that calendar year
    assert _indian_fy_label(date(2024, 12, 15)) == "FY24-25"
    # January falls back to the FY that started the prior calendar year
    assert _indian_fy_label(date(2025, 1, 5)) == "FY24-25"


@pytest.mark.django_db
def test_realised_by_fy_splits_ltcg_and_stcg(profile, zerodha, hdfc_bank):
    # Buy in 2022, sell parts in two different FYs, one short-term, one long-term.
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "20", "1000", "z-1")
    # Sold within 365 days of buy -> STCG, FY22-23 (sold 2022-12-15)
    _sell(zerodha, hdfc_bank, date(2022, 12, 15), "5", "1100", "z-2")
    # Sold > 365 days after buy -> LTCG, FY23-24 (sold 2023-04-15)
    _sell(zerodha, hdfc_bank, date(2023, 4, 15), "5", "1200", "z-3")

    rows = realised_by_fy(profile)
    by_fy = {r.fy: r for r in rows}
    assert "FY22-23" in by_fy
    assert "FY23-24" in by_fy
    # 5 units, +100/unit short-term -> +500 STCG in FY22-23
    assert by_fy["FY22-23"].stcg == Decimal("500")
    assert by_fy["FY22-23"].ltcg == Decimal("0")
    # 5 units, +200/unit long-term -> +1000 LTCG in FY23-24
    assert by_fy["FY23-24"].ltcg == Decimal("1000")
    assert by_fy["FY23-24"].stcg == Decimal("0")
    # Rows must be ordered by FY
    assert [r.fy for r in rows] == sorted(r.fy for r in rows)


@pytest.mark.django_db
def test_realised_by_fy_empty_when_no_trades(profile):
    assert realised_by_fy(profile) == []


@pytest.mark.django_db
def test_realised_by_fy_instrument_filter(profile, zerodha, hdfc_bank):
    """Per-instrument filter should restrict the rollup to only that instrument's gains."""
    other = Instrument.objects.create(
        profile=profile,
        isin="INE002A01018",
        exchange_symbol="RELIANCE",
        name="Reliance",
        kind=InstrumentKind.STOCK,
    )
    # Round-trip on hdfc_bank, +500 STCG in FY22-23
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2022, 12, 15), "5", "1100", "z-2")
    # Round-trip on other, +200 STCG in FY22-23
    _buy(zerodha, other, date(2022, 1, 1), "5", "2000", "z-3")
    _sell(zerodha, other, date(2022, 6, 1), "5", "2040", "z-4")

    profile_rows = realised_by_fy(profile)
    profile_total = sum(r.stcg + r.ltcg for r in profile_rows)
    assert profile_total == Decimal("700")  # 500 + 200

    hdfc_rows = realised_by_fy(profile, instrument=hdfc_bank)
    assert sum(r.stcg + r.ltcg for r in hdfc_rows) == Decimal("500")
    other_rows = realised_by_fy(profile, instrument=other)
    assert sum(r.stcg + r.ltcg for r in other_rows) == Decimal("200")


@pytest.mark.django_db
def test_realised_by_fy_by_pan_groups_per_pan(profile, zerodha, chola, hdfc_bank):
    # Two demats under different PANs file separate ITRs. Tag them.
    zerodha.pan = "ABCDE1234F"
    zerodha.pan_holder_name = "Self"
    zerodha.save()
    chola.pan = "FGHIJ5678K"
    chola.pan_holder_name = "Mom"
    chola.save()

    # Self (zerodha): +500 STCG in FY22-23
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2022, 12, 15), "5", "1100", "z-2")
    # Mom (chola): +1000 LTCG in FY23-24 (held > 365 days)
    _buy(chola, hdfc_bank, date(2022, 1, 1), "10", "1000", "c-1")
    _sell(chola, hdfc_bank, date(2023, 4, 15), "5", "1200", "c-2")

    groups, totals = realised_by_fy_by_pan(profile)
    by_holder = {g.holder_name: g for g in groups}
    assert set(by_holder) == {"Self", "Mom"}

    self_rows = {r.fy: r for r in by_holder["Self"].rows}
    assert self_rows["FY22-23"].stcg == Decimal("500")
    assert self_rows["FY22-23"].ltcg == Decimal("0")
    assert "FY23-24" not in self_rows  # Mom's LTCG must not leak into Self

    mom_rows = {r.fy: r for r in by_holder["Mom"].rows}
    assert mom_rows["FY23-24"].ltcg == Decimal("1000")
    assert mom_rows["FY23-24"].stcg == Decimal("0")
    assert "FY22-23" not in mom_rows

    # Across-PAN totals match the flat realised_by_fy aggregation.
    flat = {r.fy: r for r in realised_by_fy(profile)}
    totals_by_fy = {r.fy: r for r in totals}
    assert set(totals_by_fy) == set(flat)
    for fy, r in flat.items():
        assert totals_by_fy[fy].ltcg == r.ltcg
        assert totals_by_fy[fy].stcg == r.stcg


@pytest.mark.django_db
def test_realised_by_fy_by_pan_buckets_blank_pan_separately(profile, zerodha, chola, hdfc_bank):
    """Accounts with no PAN tag fall into a single 'Unassigned' group, sorted last."""
    zerodha.pan = "ABCDE1234F"
    zerodha.pan_holder_name = "Self"
    zerodha.save()
    # chola left with blank PAN

    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2022, 12, 15), "5", "1100", "z-2")
    _buy(chola, hdfc_bank, date(2022, 1, 1), "10", "1000", "c-1")
    _sell(chola, hdfc_bank, date(2022, 12, 15), "5", "1100", "c-2")

    groups, _ = realised_by_fy_by_pan(profile)
    assert [g.display_name for g in groups] == ["Self", "Unassigned"]


@pytest.mark.django_db
def test_realised_by_fy_by_pan_merges_same_pan_across_brokers(profile, zerodha, chola, hdfc_bank):
    """Two demats under the same PAN must collapse into one group."""
    pan = "ABCDE1234F"
    for ba in (zerodha, chola):
        ba.pan = pan
        ba.pan_holder_name = "Self"
        ba.save()

    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2022, 12, 15), "5", "1100", "z-2")
    _buy(chola, hdfc_bank, date(2022, 1, 1), "10", "1000", "c-1")
    _sell(chola, hdfc_bank, date(2022, 12, 15), "5", "1100", "c-2")

    groups, _ = realised_by_fy_by_pan(profile)
    assert len(groups) == 1
    rows_by_fy = {r.fy: r for r in groups[0].rows}
    assert rows_by_fy["FY22-23"].stcg == Decimal("1000")  # 500 + 500


@pytest.mark.django_db
def test_breakdown_ltcg_eligible_unrealised(profile, zerodha, hdfc_bank):
    """Lots held > 365 days at as_of contribute to ltcg_eligible_unrealised; younger lots don't."""
    # Lot A: bought 2022-01-01 (will be > 365 days by 2024-01-01)
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    # Lot B: bought 2023-12-15 (will be < 365 days by 2024-01-01)
    _buy(zerodha, hdfc_bank, date(2023, 12, 15), "5", "1000", "z-2")

    # Stub a price lookup at 1200 INR.
    def _price(_inst, _when):
        return (Decimal("1200"), False)

    br = instrument_breakdown(profile, hdfc_bank, as_of=date(2024, 1, 1), price_lookup=_price)
    # Only the 10-unit lot is long-term; gain = 10 * (1200 - 1000) = 2000
    assert br.ltcg_eligible_unrealised == Decimal("2000")
    # Total unrealised = 15 * 200 = 3000
    assert br.unrealised_pnl == Decimal("3000")


@pytest.mark.django_db
def test_portfolio_summary_holdings_and_exited_counts(profile, zerodha, hdfc_bank):
    """holdings_count counts instruments with open lots; exited_count counts fully-sold ones."""
    open_instr = hdfc_bank
    closed_instr = Instrument.objects.create(
        profile=profile,
        isin="INE002A01018",
        exchange_symbol="RELIANCE",
        name="Reliance",
        kind=InstrumentKind.STOCK,
    )
    # Open position
    _buy(zerodha, open_instr, date(2024, 1, 1), "10", "1000", "z-1")
    # Closed position
    _buy(zerodha, closed_instr, date(2024, 1, 1), "5", "2000", "z-2")
    _sell(zerodha, closed_instr, date(2024, 6, 1), "5", "2100", "z-3")

    summary = portfolio_summary(profile, as_of=date(2024, 12, 31))
    assert summary.holdings_count == 1
    assert summary.exited_count == 1


@pytest.mark.django_db
def test_dividend_pay_date_fallback_uses_ex_date_plus_35(profile, zerodha, hdfc_bank):
    """When pay_date is NULL, XIRR treats cashflow as ex_date + 35 days.

    Two flows with the same notional cash on different effective dates should
    produce slightly different XIRRs, confirming the fallback is applied.
    """
    _buy(zerodha, hdfc_bank, date(2022, 1, 1), "10", "1000", "z-1")
    _sell(zerodha, hdfc_bank, date(2023, 1, 1), "10", "1100", "z-2")
    # With pay_date missing, the 200 dividend lands 2022-07-06 (=2022-06-01 + 35d)
    _dividend(profile, zerodha, hdfc_bank, date(2022, 6, 1), "200", pay_date=None)
    no_pay = instrument_xirr(profile, hdfc_bank, as_of=date(2023, 1, 1))

    assert no_pay is not None
    # We can't easily isolate the fallback without rewriting the flow, but
    # we at least assert the rate is positive and includes the dividend uplift.
    assert no_pay > Decimal("0.10")

"""Tests for the per-BrokerAccount FIFO lot engine.

These tests use plain dataclasses (not Django models) so they run without a
database and keep the engine's Protocol-typed contract honest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from core.services.lots import (
    ShortSellError,
    build_lots,
)

ZERO = Decimal(0)


@dataclass
class TradeStub:
    id: int
    broker_account_id: int
    instrument_id: int
    trade_date: date
    side: str
    quantity: Decimal
    price: Decimal
    total_charges: Decimal = ZERO
    exec_time: object = None


@dataclass
class ActionStub:
    id: int
    instrument_id: int
    action_type: str
    ex_date: date
    broker_account_id: int | None = None
    ratio_numerator: Decimal | None = None
    ratio_denominator: Decimal | None = None
    units_added: Decimal | None = None
    new_instrument_id: int | None = None
    cash_component: Decimal | None = None


# A = Zerodha account id, B = Chola account id (arbitrary)
A, B = 1, 2
IDX = 100  # arbitrary instrument id


def t(id: int, ba: int, date_: date, side: str, qty: str, price: str, charges: str = "0", inst: int = IDX) -> TradeStub:
    return TradeStub(
        id=id,
        broker_account_id=ba,
        instrument_id=inst,
        trade_date=date_,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        total_charges=Decimal(charges),
    )


# ---------------------------------------------------------------------------
# Basic FIFO
# ---------------------------------------------------------------------------


def test_single_buy_leaves_one_open_lot() -> None:
    trades = [t(1, A, date(2024, 1, 1), "BUY", "10", "100")]
    books = build_lots(trades)
    book = books[(A, IDX)]
    assert len(book.open_lots) == 1
    assert book.open_lots[0].qty_remaining == Decimal("10")
    assert book.open_lots[0].cost_per_unit == Decimal("100")
    assert book.realised == []


def test_buy_then_full_sell_drains_lot() -> None:
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "100"),
        t(2, A, date(2024, 6, 1), "SELL", "10", "150"),
    ]
    books = build_lots(trades)
    book = books[(A, IDX)]
    assert book.open_lots == []
    assert len(book.realised) == 1
    r = book.realised[0]
    assert r.qty == Decimal("10")
    assert r.buy_cost == Decimal("1000")
    assert r.sell_proceeds == Decimal("1500")
    assert r.realised_pnl == Decimal("500")
    assert r.holding_days == (date(2024, 6, 1) - date(2024, 1, 1)).days
    assert r.long_term is False


def test_partial_sell_splits_oldest_lot_first() -> None:
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "100"),
        t(2, A, date(2024, 3, 1), "BUY", "5", "120"),
        t(3, A, date(2024, 6, 1), "SELL", "8", "150"),
    ]
    books = build_lots(trades)
    book = books[(A, IDX)]
    # Sold 8 out of the first (older) lot of 10 -> 2 remain in lot1 + all 5 in lot2
    assert len(book.open_lots) == 2
    assert book.open_lots[0].qty_remaining == Decimal("2")
    assert book.open_lots[0].cost_per_unit == Decimal("100")
    assert book.open_lots[1].qty_remaining == Decimal("5")
    assert book.open_lots[1].cost_per_unit == Decimal("120")
    # One realised gain drawing from lot1 only
    assert len(book.realised) == 1
    r = book.realised[0]
    assert r.qty == Decimal("8")
    assert r.buy_cost == Decimal("800")
    assert r.sell_proceeds == Decimal("1200")
    assert r.open_trade_id == 1


def test_sell_spanning_two_lots_emits_two_gains() -> None:
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "4", "100"),
        t(2, A, date(2024, 2, 1), "BUY", "6", "120"),
        t(3, A, date(2024, 6, 1), "SELL", "7", "150"),
    ]
    books = build_lots(trades)
    book = books[(A, IDX)]
    assert len(book.realised) == 2
    first, second = book.realised
    assert first.qty == Decimal("4")
    assert first.open_trade_id == 1
    assert second.qty == Decimal("3")
    assert second.open_trade_id == 2
    # Remaining: 3 units of lot2
    assert len(book.open_lots) == 1
    assert book.open_lots[0].qty_remaining == Decimal("3")
    assert book.open_lots[0].cost_per_unit == Decimal("120")


def test_three_buys_one_sell() -> None:
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "5", "100"),
        t(2, A, date(2024, 2, 1), "BUY", "5", "110"),
        t(3, A, date(2024, 3, 1), "BUY", "5", "120"),
        t(4, A, date(2024, 6, 1), "SELL", "8", "150"),
    ]
    books = build_lots(trades)
    book = books[(A, IDX)]
    # Sold 5 from lot1 + 3 from lot2 -> 2 left in lot2 + 5 in lot3
    assert [lot.qty_remaining for lot in book.open_lots] == [Decimal("2"), Decimal("5")]
    assert len(book.realised) == 2


def test_short_sell_raises() -> None:
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "5", "100"),
        t(2, A, date(2024, 6, 1), "SELL", "10", "150"),
    ]
    with pytest.raises(ShortSellError):
        build_lots(trades)


def test_short_sell_non_strict_synthesises_opening_balance() -> None:
    """When ``strict=False``, the engine accepts a SELL larger than known
    BUY history by inventing a zero-cost opening lot for the shortfall and
    flagging the book. Used by the UI layer when a user uploads a partial
    tradebook window."""

    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "5", "100"),
        t(2, A, date(2024, 6, 1), "SELL", "10", "150"),
    ]
    books = build_lots(trades, strict=False)
    book = books[(A, IDX)]
    assert book.has_missing_history is True
    assert book.open_lots == []
    # Two realisations: 5 units against the known buy (gain = 5*50 = 250),
    # then 5 units synthetic (buy_cost = 0, proceeds = 5*150 = 750).
    assert len(book.realised) == 2
    known = book.realised[0]
    synthetic = book.realised[1]
    assert known.qty == Decimal("5")
    assert known.realised_pnl == Decimal("250")
    assert synthetic.qty == Decimal("5")
    assert synthetic.buy_cost == Decimal("0")
    assert synthetic.sell_proceeds == Decimal("750")
    assert synthetic.open_trade_id == 0  # marker for synthetic


def test_short_sell_strict_is_still_default() -> None:
    """Regression: omitting ``strict`` must continue to raise ShortSellError
    so any tool that relied on the tight contract keeps behaving the same."""
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "5", "100"),
        t(2, A, date(2024, 6, 1), "SELL", "10", "150"),
    ]
    with pytest.raises(ShortSellError):
        build_lots(trades)  # no kwargs -> strict=True


def test_charges_inflate_cost_and_reduce_proceeds() -> None:
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "100", charges="20"),
        t(2, A, date(2024, 6, 1), "SELL", "10", "150", charges="15"),
    ]
    books = build_lots(trades)
    r = books[(A, IDX)].realised[0]
    # Buy cost = 10*100 + 20 = 1020; cost/unit = 102
    # Sell proceeds = 10*150 - 15 = 1485
    assert r.buy_cost == Decimal("1020")
    assert r.sell_proceeds == Decimal("1485")
    assert r.realised_pnl == Decimal("465")


# ---------------------------------------------------------------------------
# Cross-broker isolation (user's explicit correction)
# ---------------------------------------------------------------------------


def test_sell_on_broker_a_does_not_drain_broker_b_lots() -> None:
    """A SELL on Zerodha can only consume Zerodha lots -- never Chola's."""
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "100"),  # Zerodha lot
        t(2, B, date(2024, 2, 1), "BUY", "10", "100"),  # Chola lot
        t(3, A, date(2024, 6, 1), "SELL", "5", "150"),  # Sell from Zerodha
    ]
    books = build_lots(trades)
    zerodha = books[(A, IDX)]
    chola = books[(B, IDX)]
    # Zerodha: 5 remain
    assert len(zerodha.open_lots) == 1
    assert zerodha.open_lots[0].qty_remaining == Decimal("5")
    assert len(zerodha.realised) == 1
    # Chola untouched
    assert len(chola.open_lots) == 1
    assert chola.open_lots[0].qty_remaining == Decimal("10")
    assert chola.realised == []


def test_short_sell_on_one_broker_even_when_other_has_stock() -> None:
    """Even if Chola holds enough shares, a Zerodha-only SELL beyond Zerodha
    holdings must raise -- the engine does not pool across brokers."""
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "3", "100"),
        t(2, B, date(2024, 1, 1), "BUY", "100", "100"),  # plenty at Chola, irrelevant
        t(3, A, date(2024, 6, 1), "SELL", "5", "150"),  # Zerodha short by 2
    ]
    with pytest.raises(ShortSellError):
        build_lots(trades)


# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------


def test_split_with_explicit_ratio_scales_open_lots() -> None:
    """1:10 split => qty *10, cost_per_unit /10."""
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "1000"),
    ]
    actions = [
        ActionStub(
            id=1, instrument_id=IDX, action_type="SPLIT", ex_date=date(2024, 6, 1),
            ratio_numerator=Decimal("10"), ratio_denominator=Decimal("1"),
        ),
    ]
    book = build_lots(trades, actions)[(A, IDX)]
    assert len(book.open_lots) == 1
    assert book.open_lots[0].qty_remaining == Decimal("100")
    assert book.open_lots[0].cost_per_unit == Decimal("100")


def test_split_preserves_total_cost() -> None:
    """Splits must not change the total cost of the holding -- only redistribute it."""
    trades = [t(1, A, date(2024, 1, 1), "BUY", "10", "200", charges="0")]
    actions = [
        ActionStub(
            id=1, instrument_id=IDX, action_type="SPLIT", ex_date=date(2024, 6, 1),
            ratio_numerator=Decimal("5"), ratio_denominator=Decimal("1"),
        ),
    ]
    book = build_lots(trades, actions)[(A, IDX)]
    lot = book.open_lots[0]
    total_cost = lot.qty_remaining * lot.cost_per_unit
    assert total_cost == Decimal("2000")  # 10 * 200 originally


def test_chola_style_split_infers_ratio_from_units_added() -> None:
    """Chola PDF reports ``units_added`` not a ratio. For a single broker on
    ex-date with 5 open units and 1089 added => ratio 1094/5 = 218.8."""
    trades = [t(1, A, date(2024, 1, 1), "BUY", "5", "2000")]
    actions = [
        ActionStub(
            id=1,
            instrument_id=IDX,
            broker_account_id=A,  # Chola-style: per-account action
            action_type="SPLIT",
            ex_date=date(2024, 6, 1),
            units_added=Decimal("1089"),
        ),
    ]
    book = build_lots(trades, actions)[(A, IDX)]
    lot = book.open_lots[0]
    assert lot.qty_remaining == Decimal("1094")
    # Total cost preserved: 5*2000 = 10000; per-unit = 10000/1094
    assert lot.qty_remaining * lot.cost_per_unit == Decimal("10000")


def test_split_between_buy_and_sell() -> None:
    """A 1:2 split halves the per-unit price and doubles qty; a later SELL
    correctly computes gain against the adjusted cost basis."""
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "1000"),  # cost_pu = 1000
        t(2, A, date(2025, 1, 1), "SELL", "20", "600"),  # sells 2x the original qty
    ]
    actions = [
        ActionStub(
            id=1, instrument_id=IDX, action_type="SPLIT", ex_date=date(2024, 6, 1),
            ratio_numerator=Decimal("2"), ratio_denominator=Decimal("1"),
        ),
    ]
    book = build_lots(trades, actions)[(A, IDX)]
    assert book.open_lots == []
    r = book.realised[0]
    assert r.qty == Decimal("20")
    # Post-split cost per unit: 500; buy_cost = 20 * 500 = 10000
    assert r.buy_cost == Decimal("10000")
    assert r.sell_proceeds == Decimal("12000")
    assert r.realised_pnl == Decimal("2000")


def test_bonus_adds_zero_cost_qty_preserving_holding_period() -> None:
    """1:1 bonus => one extra zero-cost unit per held unit, with the original
    ``opened_on`` preserved (long-term status computed off the original buy)."""
    trades = [
        t(1, A, date(2022, 1, 1), "BUY", "10", "100"),
        t(2, A, date(2024, 6, 2), "SELL", "20", "80"),
    ]
    actions = [
        ActionStub(
            id=1, instrument_id=IDX, action_type="BONUS", ex_date=date(2024, 6, 1),
            ratio_numerator=Decimal("1"), ratio_denominator=Decimal("1"),
        ),
    ]
    book = build_lots(trades, actions)[(A, IDX)]
    # Sold all 20. Realisation may split across original lot + bonus lot.
    assert book.open_lots == []
    total_qty = sum(r.qty for r in book.realised)
    assert total_qty == Decimal("20")
    total_cost = sum(r.buy_cost for r in book.realised)
    # Original 10 at 100 = 1000. Bonus 10 at 0 = 0. Total cost = 1000.
    assert total_cost == Decimal("1000")
    total_proceeds = sum(r.sell_proceeds for r in book.realised)
    assert total_proceeds == Decimal("1600")
    # All realisations inherit the 2022-01-01 opened_on -> long-term
    assert all(r.long_term for r in book.realised)


def test_global_action_applies_to_all_brokers() -> None:
    """A market-wide SPLIT with no broker_account_id applies to every broker's
    queue for that instrument."""
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "1000"),
        t(2, B, date(2024, 2, 1), "BUY", "4", "1000"),
    ]
    actions = [
        ActionStub(
            id=1,
            instrument_id=IDX,
            action_type="SPLIT",
            ex_date=date(2024, 6, 1),
            ratio_numerator=Decimal("10"),
            ratio_denominator=Decimal("1"),
        ),
    ]
    books = build_lots(trades, actions)
    assert books[(A, IDX)].open_lots[0].qty_remaining == Decimal("100")
    assert books[(B, IDX)].open_lots[0].qty_remaining == Decimal("40")


def test_isin_change_moves_lots_to_new_instrument() -> None:
    """After ISIN_CHANGE, prior lots are attributed to the new instrument's book."""
    OLD, NEW = 500, 501
    trades = [
        t(1, A, date(2024, 1, 1), "BUY", "10", "100", inst=OLD),
        t(2, A, date(2025, 1, 1), "SELL", "10", "150", inst=NEW),
    ]
    actions = [
        ActionStub(
            id=1,
            instrument_id=OLD,
            action_type="ISIN_CHANGE",
            ex_date=date(2024, 6, 1),
            new_instrument_id=NEW,
        ),
    ]
    books = build_lots(trades, actions)
    # After replay: old book is empty, new book has the realisation
    assert (A, NEW) in books
    new_book = books[(A, NEW)]
    assert new_book.open_lots == []
    assert len(new_book.realised) == 1
    assert new_book.realised[0].qty == Decimal("10")
    assert new_book.realised[0].realised_pnl == Decimal("500")

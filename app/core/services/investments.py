"""Portfolio & per-instrument analytics (XIRR, realised/unrealised, CAGR).

This module is the only place that wires together ``StockTrade``,
``DividendRecord``, corporate actions, and the FIFO lot engine into the
cash-flow stream that ``xirr()`` consumes. UI layers read from here only.

All returns are in the user's ``base_currency`` (usually INR). Cross-currency
flows are converted at the flow's date via the ``FxRate`` cache; if the rate
is missing we skip that flow and record it under ``conversion_errors`` rather
than failing the whole calculation.

**Phase A scope:** the public API is complete and correct for pure in-scope
cashflows (trades + dividends). Terminal market-value inflow uses a
``price_lookup`` callable that callers inject -- in Phase A that callable
just returns ``None`` if the price service hasn't been wired up yet, which
is fine because XIRR still converges on an open-ended position by treating
the remaining cost as the terminal value (producing a conservative XIRR).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from core.models import (
    DividendRecord,
    Instrument,
    Profile,
    StockTrade,
)
from core.money import FxRateMissingError, to_base_currency
from core.services.lots import Book, build_lots
from core.services.xirr import xirr

ZERO = Decimal(0)
PAY_DATE_FALLBACK_DAYS = 35  # Zerodha says dividends credit in 30-45 days; midpoint.

PriceLookup = Callable[[Instrument, date], tuple[Decimal | None, bool]]


def _noop_price_lookup(_inst: Instrument, _when: date) -> tuple[Decimal | None, bool]:
    return (None, True)


@dataclass
class InstrumentBreakdown:
    instrument_id: int
    instrument_name: str
    qty_held: Decimal = ZERO
    avg_cost: Decimal | None = None
    invested_open: Decimal = ZERO  # remaining cost basis of still-open lots
    realised_pnl: Decimal = ZERO
    dividends: Decimal = ZERO
    current_value: Decimal | None = None
    unrealised_pnl: Decimal | None = None
    weight_pct: Decimal | None = None  # current_value / portfolio total; set by caller
    ltcg_eligible_unrealised: Decimal = ZERO  # qty * (price - cost) for lots > 365d
    xirr: Decimal | None = None
    holding_period_days: int | None = None
    # True when the FIFO engine had to synthesise an opening balance because
    # the tradebook window started after a real earlier BUY. Caller shows a
    # "buy history incomplete" badge; realised_pnl is inflated by the
    # missing cost basis.
    has_missing_history: bool = False
    conversion_errors: list[str] = field(default_factory=list)


@dataclass
class PortfolioSummary:
    total_invested_open: Decimal = ZERO
    total_current_value: Decimal = ZERO
    total_realised: Decimal = ZERO
    total_dividends: Decimal = ZERO
    total_unrealised: Decimal = ZERO
    total_ltcg_eligible_unrealised: Decimal = ZERO
    xirr: Decimal | None = None
    instruments_with_missing_history: int = 0
    holdings_count: int = 0
    exited_count: int = 0
    conversion_errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cashflow construction
# ---------------------------------------------------------------------------


def _effective_div_date(div: DividendRecord) -> date:
    return div.pay_date or (div.ex_date + timedelta(days=PAY_DATE_FALLBACK_DAYS))


def _convert(
    amount: Decimal,
    currency: str,
    base_ccy: str,
    user,
    errors: list[str],
    label: str,
) -> Decimal | None:
    try:
        return to_base_currency(amount, currency, base_ccy, user=user)
    except FxRateMissingError as e:
        errors.append(f"{label}: {e}")
        return None


def _trades_qs(profile: Profile, *, instrument=None, broker_account=None, kind=None):
    qs = StockTrade.objects.filter(profile=profile).select_related(
        "broker_account", "instrument"
    )
    if instrument is not None:
        qs = qs.filter(instrument=instrument)
    if broker_account is not None:
        qs = qs.filter(broker_account=broker_account)
    if kind is not None:
        qs = qs.filter(instrument__kind=kind)
    return qs


def _dividends_qs(profile: Profile, *, instrument=None, broker_account=None, kind=None):
    qs = DividendRecord.objects.filter(profile=profile).select_related(
        "broker_account", "instrument"
    )
    if instrument is not None:
        qs = qs.filter(instrument=instrument)
    if broker_account is not None:
        qs = qs.filter(broker_account=broker_account)
    if kind is not None:
        qs = qs.filter(instrument__kind=kind)
    return qs


def _collect_trade_flows(
    trades, base_ccy: str, user, errors: list[str]
) -> list[tuple[date, Decimal]]:
    flows: list[tuple[date, Decimal]] = []
    for tr in trades:
        converted = _convert(
            tr.net_amount,
            tr.currency,
            base_ccy,
            user,
            errors,
            label=f"trade#{tr.id}",
        )
        if converted is not None:
            flows.append((tr.trade_date, converted))
    return flows


def _collect_dividend_flows(
    dividends, base_ccy: str, user, errors: list[str]
) -> list[tuple[date, Decimal]]:
    flows: list[tuple[date, Decimal]] = []
    for d in dividends:
        converted = _convert(
            d.amount_net,
            d.currency,
            base_ccy,
            user,
            errors,
            label=f"dividend#{d.id}",
        )
        if converted is not None:
            flows.append((_effective_div_date(d), converted))
    return flows


def _terminal_flow(
    books: Iterable[Book],
    as_of: date,
    base_ccy: str,
    user,
    price_lookup: PriceLookup,
    errors: list[str],
) -> tuple[Decimal, Decimal | None]:
    """Return (terminal_market_value, per_instrument_breakdown).

    Market value for open lots uses the ``price_lookup``. When no price is
    available we fall back to the lot's cost basis so XIRR still converges
    (the implied assumption: "current value = what you paid", a conservative
    zero-return estimate on the open tail).
    """
    mv = ZERO
    any_priced = False
    # Group books by instrument so we only look up price once per instrument
    # regardless of how many broker queues hold it.
    inst_cache: dict[int, tuple[Decimal | None, bool]] = {}
    for book in books:
        if not book.open_lots:
            continue
        inst_id = book.instrument_id
        if inst_id not in inst_cache:
            inst = book.open_lots[0].instrument_id  # sanity — same as inst_id
            instrument = Instrument.objects.filter(id=inst_id).first()
            if instrument is None:
                inst_cache[inst_id] = (None, True)
            else:
                price, stale = price_lookup(instrument, as_of)
                if price is not None:
                    converted = _convert(
                        price,
                        instrument.currency,
                        base_ccy,
                        user,
                        errors,
                        label=f"price#{instrument.id}",
                    )
                    inst_cache[inst_id] = (converted, stale)
                else:
                    inst_cache[inst_id] = (None, stale)
            _ = inst  # silence linter
        price_in_base, _stale = inst_cache[inst_id]
        for lot in book.open_lots:
            if price_in_base is not None:
                mv += lot.qty_remaining * price_in_base
                any_priced = True
            else:
                # Fallback: use cost basis (already in INR at trade time)
                mv += lot.qty_remaining * lot.cost_per_unit
    return mv, None if not any_priced else mv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def portfolio_xirr(
    profile: Profile,
    *,
    as_of: date | None = None,
    broker_account=None,
    kind: str | None = None,
    price_lookup: PriceLookup = _noop_price_lookup,
) -> Decimal | None:
    """XIRR for the whole portfolio (optionally filtered by broker/kind)."""

    as_of = as_of or date.today()
    user = profile.user
    base_ccy = user.base_currency
    errors: list[str] = []

    trades = list(_trades_qs(profile, broker_account=broker_account, kind=kind))
    dividends = list(_dividends_qs(profile, broker_account=broker_account, kind=kind))
    if not trades and not dividends:
        return None

    flows = _collect_trade_flows(trades, base_ccy, user, errors)
    flows += _collect_dividend_flows(dividends, base_ccy, user, errors)

    # Terminal market value (positive inflow) from still-open lots
    books = build_lots(
        _stock_trades_as_lot_input(trades),
        _corporate_actions_as_lot_input(profile),
    
        strict=False,
    )
    mv, _priced = _terminal_flow(books.values(), as_of, base_ccy, user, price_lookup, errors)
    if mv > ZERO:
        flows.append((as_of, mv))

    return xirr(flows)


def instrument_xirr(
    profile: Profile,
    instrument: Instrument,
    *,
    as_of: date | None = None,
    broker_account=None,
    price_lookup: PriceLookup = _noop_price_lookup,
) -> Decimal | None:
    """XIRR for a single instrument across (or within) broker accounts."""

    as_of = as_of or date.today()
    user = profile.user
    base_ccy = user.base_currency
    errors: list[str] = []

    trades = list(_trades_qs(profile, instrument=instrument, broker_account=broker_account))
    dividends = list(
        _dividends_qs(profile, instrument=instrument, broker_account=broker_account)
    )
    if not trades:
        return None

    flows = _collect_trade_flows(trades, base_ccy, user, errors)
    flows += _collect_dividend_flows(dividends, base_ccy, user, errors)

    books = build_lots(
        _stock_trades_as_lot_input(trades),
        _corporate_actions_as_lot_input(profile, instrument=instrument),
    
        strict=False,
    )
    mv, _ = _terminal_flow(books.values(), as_of, base_ccy, user, price_lookup, errors)
    if mv > ZERO:
        flows.append((as_of, mv))

    return xirr(flows)


def instrument_breakdown(
    profile: Profile,
    instrument: Instrument,
    *,
    as_of: date | None = None,
    broker_account=None,
    price_lookup: PriceLookup = _noop_price_lookup,
) -> InstrumentBreakdown:
    """Full per-instrument stats: qty, avg cost, realised, dividends, XIRR, CAGR."""

    as_of = as_of or date.today()
    user = profile.user
    base_ccy = user.base_currency
    errors: list[str] = []
    br = InstrumentBreakdown(instrument_id=instrument.id, instrument_name=instrument.name)

    trades = list(_trades_qs(profile, instrument=instrument, broker_account=broker_account))
    dividends = list(
        _dividends_qs(profile, instrument=instrument, broker_account=broker_account)
    )
    if not trades and not dividends:
        return br

    books = build_lots(
        _stock_trades_as_lot_input(trades),
        _corporate_actions_as_lot_input(profile, instrument=instrument),
    
        strict=False,
    )

    qty_held = ZERO
    invested_open = ZERO
    realised_pnl = ZERO
    earliest: date | None = None
    any_missing = False
    open_lots_all: list = []
    for book in books.values():
        if book.has_missing_history:
            any_missing = True
        for lot in book.open_lots:
            qty_held += lot.qty_remaining
            invested_open += lot.qty_remaining * lot.cost_per_unit
            earliest = lot.opened_on if earliest is None else min(earliest, lot.opened_on)
            open_lots_all.append(lot)
        for r in book.realised:
            realised_pnl += r.realised_pnl

    dividends_total = ZERO
    for d in dividends:
        c = _convert(d.amount_net, d.currency, base_ccy, user, errors, f"dividend#{d.id}")
        if c is not None:
            dividends_total += c

    br.qty_held = qty_held
    br.invested_open = invested_open
    br.avg_cost = (invested_open / qty_held) if qty_held > ZERO else None
    br.realised_pnl = realised_pnl
    br.dividends = dividends_total
    br.has_missing_history = any_missing

    # Terminal value + unrealised + LTCG-eligible-unrealised
    price, _stale = price_lookup(instrument, as_of)
    price_inr: Decimal | None = None
    if price is not None:
        price_inr = _convert(price, instrument.currency, base_ccy, user, errors, "price")
    if price_inr is not None:
        br.current_value = qty_held * price_inr
        br.unrealised_pnl = br.current_value - invested_open
        ltcg_eligible = ZERO
        for lot in open_lots_all:
            if (as_of - lot.opened_on).days > 365:
                ltcg_eligible += lot.qty_remaining * (price_inr - lot.cost_per_unit)
        br.ltcg_eligible_unrealised = ltcg_eligible
    if earliest is not None:
        br.holding_period_days = (as_of - earliest).days

    # XIRR — reuse the per-instrument function so logic stays single-sourced
    br.xirr = instrument_xirr(
        profile,
        instrument,
        as_of=as_of,
        broker_account=broker_account,
        price_lookup=price_lookup,
    )

    br.conversion_errors = errors
    return br


def portfolio_summary(
    profile: Profile,
    *,
    as_of: date | None = None,
    broker_account=None,
    kind: str | None = None,
    price_lookup: PriceLookup = _noop_price_lookup,
) -> PortfolioSummary:
    """Aggregate totals + portfolio XIRR across all instruments in scope."""

    as_of = as_of or date.today()
    user = profile.user
    base_ccy = user.base_currency
    errors: list[str] = []
    summary = PortfolioSummary()

    trades = list(_trades_qs(profile, broker_account=broker_account, kind=kind))
    dividends = list(_dividends_qs(profile, broker_account=broker_account, kind=kind))
    if not trades and not dividends:
        return summary

    # Populate conversion_errors from trade-side conversions so missing FX
    # rates surface in the summary, not only in the (discarded) XIRR call.
    _collect_trade_flows(trades, base_ccy, user, errors)

    books = build_lots(
        _stock_trades_as_lot_input(trades),
        _corporate_actions_as_lot_input(profile),

        strict=False,
    )
    mv, _ = _terminal_flow(books.values(), as_of, base_ccy, user, price_lookup, errors)

    # Per-instrument LTCG-eligible unrealised needs the live price; cache it
    # so we don't hit price_lookup twice for the same instrument.
    inst_price_cache: dict[int, Decimal | None] = {}

    def _price_in_base(inst_id: int) -> Decimal | None:
        if inst_id in inst_price_cache:
            return inst_price_cache[inst_id]
        instrument = Instrument.objects.filter(id=inst_id).first()
        if instrument is None:
            inst_price_cache[inst_id] = None
            return None
        raw, _stale = price_lookup(instrument, as_of)
        if raw is None:
            inst_price_cache[inst_id] = None
            return None
        converted = _convert(
            raw, instrument.currency, base_ccy, user, errors, f"price#{inst_id}"
        )
        inst_price_cache[inst_id] = converted
        return converted

    missing_history_instruments: set[int] = set()
    instruments_with_open: set[int] = set()
    instruments_seen: set[int] = set()
    ltcg_eligible_total = ZERO
    for book in books.values():
        instruments_seen.add(book.instrument_id)
        if book.has_missing_history:
            missing_history_instruments.add(book.instrument_id)
        if book.open_lots:
            instruments_with_open.add(book.instrument_id)
        price_inr = _price_in_base(book.instrument_id) if book.open_lots else None
        for lot in book.open_lots:
            summary.total_invested_open += lot.qty_remaining * lot.cost_per_unit
            if price_inr is not None and (as_of - lot.opened_on).days > 365:
                ltcg_eligible_total += lot.qty_remaining * (price_inr - lot.cost_per_unit)
        for r in book.realised:
            summary.total_realised += r.realised_pnl

    for d in dividends:
        c = _convert(d.amount_net, d.currency, base_ccy, user, errors, f"dividend#{d.id}")
        if c is not None:
            summary.total_dividends += c

    summary.total_current_value = mv
    summary.total_unrealised = mv - summary.total_invested_open
    summary.total_ltcg_eligible_unrealised = ltcg_eligible_total
    summary.instruments_with_missing_history = len(missing_history_instruments)
    summary.holdings_count = len(instruments_with_open)
    summary.exited_count = len(instruments_seen) - len(instruments_with_open)
    summary.xirr = portfolio_xirr(
        profile,
        as_of=as_of,
        broker_account=broker_account,
        kind=kind,
        price_lookup=price_lookup,
    )
    summary.conversion_errors = errors
    return summary


# ---------------------------------------------------------------------------
# Indian-FY realised P&L grouping
# ---------------------------------------------------------------------------


def _indian_fy_label(d: date) -> str:
    """Indian FY runs 1 Apr to 31 Mar. ``date(2024, 4, 1)`` → ``"FY24-25"``."""

    if d.month >= 4:
        start = d.year
    else:
        start = d.year - 1
    return f"FY{start % 100:02d}-{(start + 1) % 100:02d}"


@dataclass
class FyRealised:
    fy: str
    ltcg: Decimal = ZERO
    stcg: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.ltcg + self.stcg


def realised_by_fy(
    profile: Profile,
    *,
    instrument=None,
    broker_account=None,
    kind: str | None = None,
) -> list[FyRealised]:
    """Group every realised gain by Indian Financial Year, split LTCG vs STCG.

    Returns rows ordered chronologically (oldest FY first). LTCG = ``r.long_term``
    (>365 days held); STCG = the rest. Synthetic zero-cost realisations from
    incomplete-history books are *included* (they show up as STCG with full
    proceeds) — the UI surfaces a missing-history caveat separately.
    """

    trades = list(
        _trades_qs(profile, instrument=instrument, broker_account=broker_account, kind=kind)
    )
    if not trades:
        return []
    books = build_lots(
        _stock_trades_as_lot_input(trades),
        _corporate_actions_as_lot_input(profile, instrument=instrument),
        strict=False,
    )
    buckets: dict[str, FyRealised] = {}
    for book in books.values():
        for r in book.realised:
            fy = _indian_fy_label(r.close_date)
            row = buckets.setdefault(fy, FyRealised(fy=fy))
            if r.long_term:
                row.ltcg += r.realised_pnl
            else:
                row.stcg += r.realised_pnl
    return sorted(buckets.values(), key=lambda x: x.fy)


# ---------------------------------------------------------------------------
# Glue: map Django models to the Protocol-typed inputs of ``build_lots``.
# ---------------------------------------------------------------------------


def _stock_trades_as_lot_input(trades: Iterable[StockTrade]) -> list[StockTrade]:
    """``StockTrade`` already matches the ``TradeLike`` Protocol shape -- the
    FK ids (``broker_account_id``, ``instrument_id``) are auto-generated by
    Django and the ``side`` / ``quantity`` / ``price`` / ``total_charges`` /
    ``trade_date`` / ``exec_time`` fields line up exactly. Returning the list
    as-is is the simplest thing and the engine will use it via duck-typing.
    """
    return list(trades)


def _corporate_actions_as_lot_input(profile: Profile, *, instrument=None):
    from core.models import CorporateAction

    qs = CorporateAction.objects.filter(profile=profile)
    if instrument is not None:
        qs = qs.filter(instrument=instrument)
    return list(qs)

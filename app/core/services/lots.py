"""Per-broker-account FIFO lot engine.

Rebuilt on demand from the immutable trade + corporate-action ledger -- never
persisted. Given a stream of trades and corp actions, returns for each
``(broker_account_id, instrument_id)`` book the list of still-open ``Lot``
records and the chronological list of ``RealisedGain`` events emitted by
SELLs draining those lots.

Key invariants:

* Lots are keyed by *both* broker account and instrument. The same ISIN held
  in Zerodha and in Chola are two independent queues -- a SELL in one cannot
  draw down the other.
* FIFO: the oldest open BUY is drained first. Bonus shares keep their
  parent lot's ``opened_on`` for holding-period / tax purposes.
* Corporate actions apply at the *start* of their ``ex_date`` (before any
  trades that same day) and only affect lots opened strictly earlier.

The engine is pure: it accepts anything that quacks like a ``TradeLike`` /
``ActionLike`` via Protocol, so tests can feed in plain dataclasses without
a DB.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol

ZERO = Decimal(0)
ONE = Decimal(1)


class ShortSellError(ValueError):
    """A SELL tried to draw more qty than is open in that (broker, instrument) book."""

    def __init__(
        self, broker_account_id: int, instrument_id: int, trade_date: date, shortfall: Decimal
    ):
        super().__init__(
            f"Short sell: broker_account={broker_account_id} instrument={instrument_id} "
            f"on {trade_date}, {shortfall} units short"
        )
        self.broker_account_id = broker_account_id
        self.instrument_id = instrument_id
        self.trade_date = trade_date
        self.shortfall = shortfall


class TradeLike(Protocol):
    id: int
    broker_account_id: int
    instrument_id: int
    trade_date: date
    exec_time: datetime | None
    side: str
    quantity: Decimal
    price: Decimal
    total_charges: Decimal


class ActionLike(Protocol):
    id: int
    instrument_id: int
    broker_account_id: int | None
    action_type: str
    ex_date: date
    ratio_numerator: Decimal | None
    ratio_denominator: Decimal | None
    units_added: Decimal | None
    new_instrument_id: int | None
    cash_component: Decimal | None


@dataclass
class Lot:
    broker_account_id: int
    instrument_id: int
    open_trade_id: int
    opened_on: date
    qty_remaining: Decimal
    cost_per_unit: Decimal


@dataclass
class RealisedGain:
    broker_account_id: int
    instrument_id: int
    open_trade_id: int
    close_trade_id: int
    close_date: date
    qty: Decimal
    buy_cost: Decimal
    sell_proceeds: Decimal
    realised_pnl: Decimal
    holding_days: int
    long_term: bool


@dataclass
class Book:
    """Per-(broker_account, instrument) FIFO state after replay."""

    broker_account_id: int
    instrument_id: int
    open_lots: list[Lot] = field(default_factory=list)
    realised: list[RealisedGain] = field(default_factory=list)
    # True when a SELL drew more qty than was visible in this ledger and we
    # synthesised a zero-cost opening lot to keep the math going. Typical
    # cause: the user's broker tradebook window is narrower than their
    # actual holding history. UI surfaces this as a "buy history incomplete"
    # warning alongside the instrument.
    has_missing_history: bool = False


BookKey = tuple[int, int]  # (broker_account_id, instrument_id)


_EXEC_TIME_MIN = datetime.min.replace(tzinfo=timezone.utc)


def _trade_sort_key(t: TradeLike) -> tuple:
    exec_time = getattr(t, "exec_time", None)
    if exec_time is not None and exec_time.tzinfo is None:
        exec_time = exec_time.replace(tzinfo=timezone.utc)
    return (t.trade_date, exec_time or _EXEC_TIME_MIN, t.id)


def _action_sort_key(a: ActionLike) -> tuple:
    return (a.ex_date, a.id)


def _cost_per_unit_buy(qty: Decimal, price: Decimal, charges: Decimal) -> Decimal:
    return (qty * price + charges) / qty


def _proceeds_per_unit_sell(qty: Decimal, price: Decimal, charges: Decimal) -> Decimal:
    return (qty * price - charges) / qty


def _apply_buy(queues: dict[BookKey, deque[Lot]], t: TradeLike) -> None:
    key: BookKey = (t.broker_account_id, t.instrument_id)
    cost_pu = _cost_per_unit_buy(t.quantity, t.price, t.total_charges)
    queues[key].append(
        Lot(
            broker_account_id=t.broker_account_id,
            instrument_id=t.instrument_id,
            open_trade_id=t.id,
            opened_on=t.trade_date,
            qty_remaining=t.quantity,
            cost_per_unit=cost_pu,
        )
    )


def _apply_sell(
    queues: dict[BookKey, deque[Lot]],
    realised: dict[BookKey, list[RealisedGain]],
    missing_history: set[BookKey],
    t: TradeLike,
    *,
    strict: bool,
) -> None:
    key: BookKey = (t.broker_account_id, t.instrument_id)
    queue = queues[key]
    remaining = t.quantity
    sell_pu = _proceeds_per_unit_sell(t.quantity, t.price, t.total_charges)
    while remaining > ZERO and queue:
        lot = queue[0]
        take = min(lot.qty_remaining, remaining)
        buy_cost = take * lot.cost_per_unit
        proceeds = take * sell_pu
        holding = (t.trade_date - lot.opened_on).days
        realised[key].append(
            RealisedGain(
                broker_account_id=t.broker_account_id,
                instrument_id=t.instrument_id,
                open_trade_id=lot.open_trade_id,
                close_trade_id=t.id,
                close_date=t.trade_date,
                qty=take,
                buy_cost=buy_cost,
                sell_proceeds=proceeds,
                realised_pnl=proceeds - buy_cost,
                holding_days=holding,
                long_term=holding > 365,
            )
        )
        lot.qty_remaining -= take
        remaining -= take
        if lot.qty_remaining == ZERO:
            queue.popleft()
    if remaining <= ZERO:
        return
    if strict:
        raise ShortSellError(t.broker_account_id, t.instrument_id, t.trade_date, remaining)
    # Non-strict: the broker tradebook window starts after some earlier BUYs
    # we don't have. Synthesise a zero-cost realisation for the shortfall so
    # the ledger balances; mark the book so the UI can warn.
    proceeds = remaining * sell_pu
    realised[key].append(
        RealisedGain(
            broker_account_id=t.broker_account_id,
            instrument_id=t.instrument_id,
            open_trade_id=0,  # synthetic -- no source trade
            close_trade_id=t.id,
            close_date=t.trade_date,
            qty=remaining,
            buy_cost=ZERO,
            sell_proceeds=proceeds,
            realised_pnl=proceeds,  # treat as pure gain; documents the gap
            holding_days=0,
            long_term=False,
        )
    )
    missing_history.add(key)


def _books_affected(
    queues: dict[BookKey, deque[Lot]], action: ActionLike
) -> list[BookKey]:
    if action.broker_account_id is None:
        return [k for k in list(queues.keys()) if k[1] == action.instrument_id]
    return [(action.broker_account_id, action.instrument_id)]


def _resolve_ratio(
    action: ActionLike, open_qty: Decimal
) -> Decimal | None:
    """Resolve SPLIT/BONUS ratio either from explicit numerator/denominator or
    by inferring from ``units_added`` against current open quantity.

    Returns ``None`` when no ratio is derivable (e.g. action reports neither).
    """
    num, den = action.ratio_numerator, action.ratio_denominator
    if num is not None and den is not None and den != ZERO:
        return Decimal(num) / Decimal(den)
    if action.units_added is not None and open_qty > ZERO:
        return (open_qty + Decimal(action.units_added)) / open_qty
    return None


def _apply_split(
    queues: dict[BookKey, deque[Lot]], action: ActionLike
) -> None:
    for key in _books_affected(queues, action):
        queue = queues[key]
        open_qty = sum(
            (lot.qty_remaining for lot in queue if lot.opened_on < action.ex_date), ZERO
        )
        ratio = _resolve_ratio(action, open_qty)
        if ratio is None or ratio == ZERO:
            continue
        for lot in queue:
            if lot.opened_on < action.ex_date:
                lot.qty_remaining *= ratio
                lot.cost_per_unit /= ratio


def _apply_bonus(
    queues: dict[BookKey, deque[Lot]], action: ActionLike
) -> None:
    for key in _books_affected(queues, action):
        queue = queues[key]
        open_qty = sum(
            (lot.qty_remaining for lot in queue if lot.opened_on < action.ex_date), ZERO
        )
        ratio = _resolve_ratio(action, open_qty)
        if ratio is None or ratio == ZERO:
            continue
        for lot in list(queue):
            if lot.opened_on >= action.ex_date:
                continue
            bonus_qty = lot.qty_remaining * ratio
            if bonus_qty > ZERO:
                queue.append(
                    Lot(
                        broker_account_id=lot.broker_account_id,
                        instrument_id=lot.instrument_id,
                        open_trade_id=lot.open_trade_id,
                        opened_on=lot.opened_on,
                        qty_remaining=bonus_qty,
                        cost_per_unit=ZERO,
                    )
                )


def _apply_isin_change(
    queues: dict[BookKey, deque[Lot]], action: ActionLike
) -> None:
    if action.new_instrument_id is None:
        return
    ratio = ONE
    if action.ratio_numerator and action.ratio_denominator:
        ratio = Decimal(action.ratio_numerator) / Decimal(action.ratio_denominator)
    for key in _books_affected(queues, action):
        old_queue = queues.get(key)
        if not old_queue:
            continue
        new_key: BookKey = (key[0], action.new_instrument_id)
        new_queue = queues[new_key]
        while old_queue:
            lot = old_queue.popleft()
            if lot.opened_on > action.ex_date:
                # Trade happened after the ISIN change -- leave as-is
                new_queue.append(lot)
                continue
            lot.instrument_id = action.new_instrument_id
            lot.qty_remaining *= ratio
            if ratio != ZERO:
                lot.cost_per_unit /= ratio
            new_queue.append(lot)


def _apply_action(queues: dict[BookKey, deque[Lot]], action: ActionLike) -> None:
    atype = action.action_type
    if atype in ("SPLIT",):
        _apply_split(queues, action)
    elif atype == "BONUS":
        _apply_bonus(queues, action)
    elif atype in ("ISIN_CHANGE", "MERGER"):
        _apply_isin_change(queues, action)
    # BUYBACK, DEMERGER, and other types are intentionally no-ops in Phase A.


def build_lots(
    trades: Iterable[TradeLike],
    actions: Iterable[ActionLike] = (),
    *,
    strict: bool = True,
) -> dict[BookKey, Book]:
    """Replay ``trades`` + ``actions`` into per-book FIFO state.

    Trades are processed in ``(trade_date, exec_time, id)`` order. Actions on
    the same day apply *before* trades on that day so a trade on the ex-date
    sees the post-action lot state.

    ``strict=True`` (default) raises ``ShortSellError`` when a SELL exceeds
    the known BUY history. ``strict=False`` synthesises a zero-cost opening
    balance for the shortfall and flags the Book with
    ``has_missing_history=True`` -- used by the UI layer where partial
    broker tradebook windows are common.
    """

    trades_list = sorted(trades, key=_trade_sort_key)
    actions_list = sorted(actions, key=_action_sort_key)

    # Merge into one timeline. Actions sort before trades on the same day
    # (tuple element 1: 0 = action, 1 = trade).
    events: list[tuple[date, int, int, object]] = []
    for a in actions_list:
        events.append((a.ex_date, 0, a.id, a))
    for t in trades_list:
        events.append((t.trade_date, 1, t.id, t))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    queues: dict[BookKey, deque[Lot]] = defaultdict(deque)
    realised: dict[BookKey, list[RealisedGain]] = defaultdict(list)
    missing_history: set[BookKey] = set()

    for _, kind, _, obj in events:
        if kind == 0:
            _apply_action(queues, obj)  # type: ignore[arg-type]
            continue
        trade: TradeLike = obj  # type: ignore[assignment]
        side = getattr(trade, "side", "").upper()
        if side == "BUY":
            _apply_buy(queues, trade)
        elif side == "SELL":
            _apply_sell(queues, realised, missing_history, trade, strict=strict)
        else:
            raise ValueError(f"Unknown trade side: {side!r}")

    books: dict[BookKey, Book] = {}
    all_keys = set(queues.keys()) | set(realised.keys())
    for key in all_keys:
        ba_id, inst_id = key
        open_lots = [lot for lot in queues.get(key, ()) if lot.qty_remaining > ZERO]
        books[key] = Book(
            broker_account_id=ba_id,
            instrument_id=inst_id,
            open_lots=open_lots,
            realised=list(realised.get(key, [])),
            has_missing_history=key in missing_history,
        )
    return books

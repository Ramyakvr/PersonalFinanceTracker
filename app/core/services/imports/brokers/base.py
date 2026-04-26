"""Broker adapter contract + normalized dataclasses.

Each broker adapter parses its native tradebook / dividend / corporate-action
file and yields the normalized dataclasses defined here. The upstream service
(``core.services.imports.tradebook``) is responsible for persisting those
records into the DB, dedup-by-trade-ref, FX conversion at import time, etc.

Adapters are pure parsers: no database access, no HTTP, no filesystem writes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

ZERO = Decimal(0)


@dataclass
class NormalizedTrade:
    broker_key: str
    account_label: str
    trade_ref: str
    trade_date: date
    isin: str
    symbol: str
    name: str
    side: str  # BUY | SELL
    quantity: Decimal
    price: Decimal
    instrument_kind: str = "STOCK"  # STOCK | MF -- drives Instrument.kind on upsert
    exec_time: datetime | None = None
    brokerage: Decimal = ZERO
    stt: Decimal = ZERO
    gst: Decimal = ZERO
    stamp_duty: Decimal = ZERO
    sebi_charges: Decimal = ZERO
    exchange_charges: Decimal = ZERO
    total_charges: Decimal = ZERO
    currency: str = "INR"
    off_market: bool = False
    exchange: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def net_amount(self) -> Decimal:
        """Signed cashflow -- BUY is negative, SELL is positive."""
        notional = self.quantity * self.price
        if self.side == "BUY":
            return -(notional + self.total_charges)
        return notional - self.total_charges


@dataclass
class NormalizedDividend:
    broker_key: str
    account_label: str
    isin: str
    symbol: str
    ex_date: date
    amount_net: Decimal
    amount_gross: Decimal = ZERO
    tds: Decimal = ZERO
    pay_date: date | None = None
    dividend_per_share: Decimal | None = None
    quantity: Decimal | None = None
    currency: str = "INR"
    name: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class NormalizedCA:
    broker_key: str
    account_label: str
    isin: str
    symbol: str
    action_type: str  # SPLIT | BONUS | MERGER | BUYBACK | DEMERGER | ISIN_CHANGE
    ex_date: date
    name: str = ""
    ratio_numerator: Decimal | None = None
    ratio_denominator: Decimal | None = None
    units_added: Decimal | None = None
    cash_component: Decimal | None = None
    new_isin: str = ""
    raw: dict = field(default_factory=dict)


@runtime_checkable
class BrokerAdapter(Protocol):
    """Contract a broker module exposes. Implementations are stateless singletons."""

    key: str
    display_name: str
    # File extensions this adapter knows how to ingest (lowercase, leading dot).
    tradebook_extensions: tuple[str, ...]
    dividend_extensions: tuple[str, ...]

    def parse_tradebook(self, file_bytes: bytes) -> Iterable[NormalizedTrade]:
        ...

    def parse_dividends(self, file_bytes: bytes) -> Iterable[NormalizedDividend]:
        ...

    def parse_corporate_actions(self, file_bytes: bytes) -> Iterable[NormalizedCA]:
        ...

    def parse_client_id(self, file_bytes: bytes) -> str:
        """Return the broker-issued client / account ID printed in the file's
        preamble. Used to auto-label the BrokerAccount on import. Return ``""``
        when the file does not carry one.
        """
        ...


class BrokerFormatError(ValueError):
    """Raised when a file does not match the expected broker format."""

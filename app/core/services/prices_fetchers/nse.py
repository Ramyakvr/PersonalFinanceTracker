"""NSE bhavcopy price fetcher.

The NSE publishes a daily equity bhavcopy CSV at
``https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv``.

Columns (verified against the live file)::

    SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE,
    LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY,
    TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER

The bhavcopy does NOT include an ISIN column, so we key on ``SYMBOL``
and resolve to a local ``Instrument`` via its ``exchange_symbol`` field.
Instruments with a blank ``exchange_symbol`` (none today, but possible
for OCR-only Chola rows) cannot be priced through this fetcher.

This module is test-first: the ``fetch_equity_prices`` public function
accepts an injectable ``loader`` so tests feed deterministic bytes
without hitting the network. The real loader downloads today's
bhavcopy (with a T-1 fallback on weekends / holidays).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.models import Instrument

ZERO = Decimal(0)

# Public archival URL template. NSE occasionally changes this; when it
# breaks we swap it in one place.
BHAVCOPY_URL_TEMPLATE = (
    "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"
)
MAX_FALLBACK_DAYS = 5

Loader = Callable[[date], bytes | None]


def _default_loader(for_date: date) -> bytes | None:
    """Fetch the bhavcopy CSV for ``for_date``. Returns ``None`` on 404.

    Kept thin so tests can replace it with ``lambda d: FIXTURE_BYTES``.
    The real fetch requires a User-Agent header -- NSE rejects bare requests.
    """

    import urllib.error
    import urllib.request

    url = BHAVCOPY_URL_TEMPLATE.format(ddmmyyyy=for_date.strftime("%d%m%Y"))
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (personal-finance-tracker; local-first)",
            "Accept": "text/csv",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def parse_bhavcopy(csv_bytes: bytes) -> dict[str, tuple[Decimal, date]]:
    """Parse bhavcopy CSV bytes -> {SYMBOL: (close_price, as_of_date)}.

    The NSE bhavcopy CSV exposes SYMBOL but not ISIN, so the caller must
    resolve SYMBOL to a local Instrument via ``Instrument.exchange_symbol``.
    """

    text = csv_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    prices: dict[str, tuple[Decimal, date]] = {}
    for raw in reader:
        # NSE CSV headers come with whitespace padding. Normalise.
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        series = row.get("SERIES", "").upper()
        # Tradeable cash-segment series for retail portfolios:
        #   EQ  - regular equity
        #   BE  - trade-to-trade equity (T1 settlement)
        #   SM  - SME platform
        #   ST  - SME-Emerge / sahaj
        #   IV  - investment vehicles (InvITs like PGINVIT, IRBINVIT)
        #   RR  - real-estate / similar trusts (EMBASSY, MINDSPACE, BIRET)
        # GS / GB are government securities; not in scope for now.
        if series not in ("EQ", "BE", "SM", "ST", "IV", "RR"):
            continue
        symbol = row.get("SYMBOL", "").upper()
        if not symbol:
            continue
        try:
            close = Decimal(row.get("CLOSE_PRICE") or row.get("LAST_PRICE") or "0")
        except (InvalidOperation, ValueError):
            continue
        if close <= ZERO:
            continue
        try:
            as_of = _parse_nse_date(row.get("DATE1", ""))
        except ValueError:
            continue
        prices[symbol] = (close, as_of)
    return prices


def _parse_nse_date(raw: str) -> date:
    from datetime import datetime

    raw = raw.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized NSE date: {raw!r}")


def fetch_equity_prices(
    instruments: list[Instrument],
    *,
    loader: Loader | None = None,
    today: date | None = None,
) -> list[tuple[Instrument, Decimal, str, date]]:
    """Return ``(instrument, price, currency, as_of)`` rows for equity instruments.

    Walks back up to ``MAX_FALLBACK_DAYS`` business days from ``today`` to
    handle weekends / market holidays. The first bhavcopy with data for
    any of the requested SYMBOLs wins. Instruments with a blank
    ``exchange_symbol`` are silently skipped (the bhavcopy is keyed on
    SYMBOL, so there is no way to resolve them).
    """

    if not instruments:
        return []
    if loader is None:
        loader = _default_loader
    if today is None:
        today = timezone.localdate()

    # Multiple Instrument rows can share a symbol (ISIN drift after a
    # corporate action, or pre-merge duplicates). Map each symbol to a list
    # so every row receives a tick instead of only the last one inserted.
    symbol_to_instruments: dict[str, list[Instrument]] = {}
    for inst in instruments:
        sym = (inst.exchange_symbol or "").upper()
        if sym:
            symbol_to_instruments.setdefault(sym, []).append(inst)

    if not symbol_to_instruments:
        return []

    cursor = today
    for _ in range(MAX_FALLBACK_DAYS + 1):
        if cursor.weekday() >= 5:  # skip weekends
            cursor -= timedelta(days=1)
            continue
        blob = loader(cursor)
        if blob is None:
            cursor -= timedelta(days=1)
            continue
        by_symbol = parse_bhavcopy(blob)
        if not by_symbol:
            cursor -= timedelta(days=1)
            continue
        results: list[tuple[Instrument, Decimal, str, date]] = []
        for symbol, (price, as_of) in by_symbol.items():
            for inst in symbol_to_instruments.get(symbol, ()):
                results.append((inst, price, "INR", as_of))
        return results
    return []

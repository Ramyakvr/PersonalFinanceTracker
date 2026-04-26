"""Cholamandalam Securities PDF parser.

Chola ships a single ``TransactionReport.pdf`` per account that mixes BUY,
SELL, DIVIDEND, SPLIT, and BONUS rows in one chronological ledger.
Columns::

    Transaction Date | Exchange | ISIN | Company Name
    | Transaction Type | Quantity | Transaction Price | Net Amount

Per-type shape:

* ``BUY`` / ``SELL`` — Quantity, Price, and Net Amount are populated.
  ``Net Amount == Quantity * Price`` (Chola does not break out charges).
* ``DIVIDEND`` — ``Quantity == 0``, ``Price`` is per-share, ``Net Amount``
  is total paid. The **Transaction Date is the pay-date** (bank credit
  date); there is no separate ex-date so the ex-date is left unset and
  the XIRR builder uses ``pay_date`` directly.
* ``SPLIT`` / ``BONUS`` — ``Price == 0``, ``Net Amount == 0``,
  ``Quantity`` is the number of units added. The lot engine infers the
  ratio from the broker's holdings on ``ex_date``.

Quirks handled:

* ``(Off Market)`` marker appears inside the Transaction Date cell
  (e.g. ``"07-Oct-2021 (Off\\nMarket)"``). We strip it and set
  ``off_market=True`` on the resulting trade.
* Company names wrap across PDF lines (``"Britannia Industries\\nLtd"``).
  We collapse newlines to a single space.
* Date format is ``DD-MMM-YYYY``.
* Header row only appears on page 1; subsequent pages continue with data.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pdfplumber

from core.services.imports.brokers.base import (
    BrokerFormatError,
    NormalizedCA,
    NormalizedDividend,
    NormalizedTrade,
)

ZERO = Decimal(0)

EXPECTED_HEADER = [
    "Transaction Date",
    "Exchange",
    "ISIN",
    "Company Name",
    "Transaction Type",
    "Quantity",
    "Transaction Price",
    "Net Amount",
]

TYPE_BUY = "BUY"
TYPE_SELL = "SELL"
TYPE_DIVIDEND = "DIVIDEND"
TYPE_SPLIT = "SPLIT"
TYPE_BONUS = "BONUS"

TRADE_TYPES = {TYPE_BUY, TYPE_SELL}
ACTION_TYPES = {TYPE_SPLIT, TYPE_BONUS}


def _extract_all_rows(file_bytes: bytes) -> list[list[str | None]]:
    """Return every row from every table across every page, preserving order.

    The first row of the first page's table is expected to be the header;
    subsequent pages repeat no header and continue with data rows.
    """
    try:
        pdf = pdfplumber.open(BytesIO(file_bytes))
    except Exception as exc:  # broad: pdfplumber raises varied exception types
        raise BrokerFormatError(f"Not a valid PDF: {exc}") from exc
    try:
        rows: list[list[str | None]] = []
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                rows.extend(table)
    finally:
        pdf.close()
    return rows


def _strip(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def _to_decimal(value) -> Decimal:
    s = _strip(value).replace(",", "")
    if not s:
        return ZERO
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise BrokerFormatError(f"Not a decimal: {value!r}") from exc


def _parse_date(value) -> tuple[date, bool]:
    """Return ``(date, off_market)``. Strips a trailing ``(Off Market)`` marker."""
    s = _strip(value)
    off_market = False
    if "(off market)" in s.lower():
        off_market = True
        # Remove the parenthesised marker wherever it sits inside the cell.
        idx = s.lower().find("(off market)")
        s = (s[:idx] + s[idx + len("(off market)") :]).strip()
    try:
        return datetime.strptime(s, "%d-%b-%Y").date(), off_market
    except ValueError as exc:
        raise BrokerFormatError(f"Unrecognized date: {value!r}") from exc


def _validate_header(row: list, filename_hint: str) -> bool:
    if not row:
        return False
    header = [_strip(c) for c in row]
    if len(header) < len(EXPECTED_HEADER):
        return False
    return header[: len(EXPECTED_HEADER)] == EXPECTED_HEADER


class CholaAdapter:
    key = "chola"
    display_name = "Cholamandalam Securities"
    tradebook_extensions: tuple[str, ...] = (".pdf",)
    dividend_extensions: tuple[str, ...] = (".pdf",)

    # -- internal -----------------------------------------------------------

    def _parsed_rows(self, file_bytes: bytes) -> list[dict]:
        """Parse the PDF into a list of row dicts keyed by the 8 Chola columns.

        Skips the header row; drops malformed rows (wrong column count or
        bad date); attaches an ``occurrence`` counter scoped to each unique
        ``(date, isin, type, quantity, price)`` bucket. The first time a
        bucket is seen ``occurrence == 1``; identical rows that follow get
        2, 3, ... This is the dedup key used by ``trade_ref``: rows with
        unique fundamentals always resolve to ``occurrence = 1``, so the
        ref is invariant under PDF row reordering. Rows with identical
        fundamentals are economically fungible; if Chola regenerates the
        PDF with such rows swapped, the *set* of refs is unchanged so the
        re-import remains idempotent. ``seq`` is kept on the record only
        as opaque audit metadata in ``raw_row_json``.
        """
        raw_rows = _extract_all_rows(file_bytes)
        if not raw_rows:
            raise BrokerFormatError("No tables found in PDF.")
        if not _validate_header(raw_rows[0], "tradebook.pdf"):
            raise BrokerFormatError(f"Expected Chola header row, got: {raw_rows[0]}")

        parsed: list[dict] = []
        occurrence_count: dict[tuple, int] = {}
        for seq, raw in enumerate(raw_rows[1:], start=1):
            if not raw or len(raw) < len(EXPECTED_HEADER):
                continue
            cells = {name: _strip(raw[i]) for i, name in enumerate(EXPECTED_HEADER)}
            if not cells["Transaction Type"]:
                continue
            try:
                trade_date, off_market = _parse_date(raw[0])
            except BrokerFormatError:
                continue
            try:
                quantity = _to_decimal(cells["Quantity"])
                price = _to_decimal(cells["Transaction Price"])
                net_amount = _to_decimal(cells["Net Amount"])
            except BrokerFormatError:
                continue
            type_ = cells["Transaction Type"].upper()
            bucket = (trade_date, cells["ISIN"], type_, quantity, price)
            occurrence_count[bucket] = occurrence_count.get(bucket, 0) + 1
            parsed.append(
                {
                    "seq": seq,
                    "occurrence": occurrence_count[bucket],
                    "date": trade_date,
                    "off_market": off_market,
                    "exchange": cells["Exchange"],
                    "isin": cells["ISIN"],
                    "name": cells["Company Name"],
                    "type": type_,
                    "quantity": quantity,
                    "price": price,
                    "net_amount": net_amount,
                }
            )
        return parsed

    # -- public adapter API -------------------------------------------------

    def parse_tradebook(
        self, file_bytes: bytes, *, account_label: str = "Main"
    ) -> Iterable[NormalizedTrade]:
        for row in self._parsed_rows(file_bytes):
            if row["type"] not in TRADE_TYPES:
                continue
            if row["quantity"] <= ZERO or row["price"] <= ZERO:
                continue
            trade_ref = (
                f"chola:{row['date'].isoformat()}:{row['isin']}:"
                f"{row['type']}:{row['quantity']}:{row['price']}:{row['occurrence']}"
            )
            yield NormalizedTrade(
                broker_key=self.key,
                account_label=account_label,
                trade_ref=trade_ref,
                trade_date=row["date"],
                exec_time=None,
                isin=row["isin"],
                # Chola reports company name but not an exchange ticker --
                # leave ``symbol`` blank so the Instrument dedupes on ISIN
                # and the long name lives in the ``name`` field.
                symbol="",
                name=row["name"],
                side=row["type"],
                quantity=row["quantity"],
                price=row["price"],
                currency="INR",
                off_market=row["off_market"],
                exchange=row["exchange"],
                raw={"seq": row["seq"], "source": "chola_pdf"},
            )

    def parse_dividends(
        self, file_bytes: bytes, *, account_label: str = "Main"
    ) -> Iterable[NormalizedDividend]:
        for row in self._parsed_rows(file_bytes):
            if row["type"] != TYPE_DIVIDEND:
                continue
            if row["net_amount"] <= ZERO:
                continue
            yield NormalizedDividend(
                broker_key=self.key,
                account_label=account_label,
                isin=row["isin"],
                # Chola PDFs don't carry an exchange ticker. Earlier versions
                # of this adapter passed the company name in ``symbol``,
                # which the importer then wrote into Instrument.exchange_symbol
                # whenever a dividend row arrived before the matching trade --
                # that is what produced rows like ``exchange_symbol='Tata
                # Steel Ltd'`` and broke NSE bhavcopy lookups. Send blank
                # symbol; route the company name via the dedicated ``name``
                # field instead.
                symbol="",
                name=row["name"],
                # Chola prints the bank-credit date; treat it as pay-date.
                # The DB's DividendRecord requires ex_date so we use the same
                # date there; the XIRR builder will prefer pay_date anyway.
                ex_date=row["date"],
                pay_date=row["date"],
                amount_gross=row["net_amount"],
                amount_net=row["net_amount"],
                dividend_per_share=row["price"] if row["price"] > ZERO else None,
                quantity=None,
                currency="INR",
                raw={"seq": row["seq"], "source": "chola_pdf"},
            )

    def parse_client_id(self, file_bytes: bytes) -> str:
        """Pull the trailing client code off the customer name line.

        Chola's PDF preamble carries one line of the shape
        ``"<NAME IN ALL CAPS> - <CLIENT_CODE>"`` followed by the postal
        address. We match the last ``- TOKEN`` on any line where ``TOKEN``
        starts with a letter (this rejects the registered-office line,
        which ends with ``-<phone>`` and would otherwise misfire). Returns
        ``""`` when no such pattern matches.
        """
        try:
            pdf = pdfplumber.open(BytesIO(file_bytes))
        except Exception:  # noqa: BLE001 -- broken PDF -> no client id
            return ""
        try:
            text = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        finally:
            pdf.close()
        for line in text.splitlines():
            m = re.search(r"-\s*([A-Z][A-Z0-9]{2,11})\s*$", line.strip())
            if m:
                return m.group(1).upper()
        return ""

    def parse_corporate_actions(
        self, file_bytes: bytes, *, account_label: str = "Main"
    ) -> Iterable[NormalizedCA]:
        for row in self._parsed_rows(file_bytes):
            if row["type"] not in ACTION_TYPES:
                continue
            if row["quantity"] <= ZERO:
                continue
            yield NormalizedCA(
                broker_key=self.key,
                account_label=account_label,
                isin=row["isin"],
                # Same reason as parse_dividends: blank to keep the company
                # name out of Instrument.exchange_symbol on first-touch import.
                symbol="",
                name=row["name"],
                action_type=row["type"],
                ex_date=row["date"],
                # Chola doesn't report a ratio -- only units added. The lot
                # engine infers the ratio against the broker's open qty.
                ratio_numerator=None,
                ratio_denominator=None,
                units_added=row["quantity"],
                raw={"seq": row["seq"], "source": "chola_pdf"},
            )

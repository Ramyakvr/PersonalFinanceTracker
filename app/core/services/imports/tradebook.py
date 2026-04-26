"""Broker tradebook / dividend import services.

High-level glue between the broker adapters (``brokers/``) and the Django
models (``StockTrade``, ``DividendRecord``, ``Instrument``,
``BrokerAccount``). These are the entry points wired into the UI's import
page.

Idempotency: re-importing the same file produces zero new rows. StockTrade
has a unique constraint on ``(broker_account, trade_ref)``, DividendRecord
on ``(profile, broker_account, instrument, ex_date, amount_gross)``, and
CorporateAction on ``(broker_account, instrument, action_type, ex_date)``.
All three dedup keys are scoped per broker_account, so the same dividend
or split reported by two brokers (because the user holds the ISIN in
both demats) survives as two rows -- one per broker -- since the
per-account ``units_added`` / cash flow are independent. We use
``get_or_create`` so duplicates are silently skipped; rows that already
existed are counted under ``ImportResult.skipped`` (``updated`` stays at
0 -- broker imports never overwrite existing rows).

Instrument upsert: we match on ``(profile, isin)`` when the broker
supplied an ISIN. When a later import arrives with a non-blank
``exchange_symbol`` / ``name`` and the existing Instrument row still has
those fields blank, we fill them in -- we never overwrite non-blank
metadata.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction as db_tx

from core.models import (
    BrokerAccount,
    CorporateAction,
    DividendRecord,
    DividendSource,
    ImportJob,
    ImportStatus,
    Instrument,
    InstrumentKind,
    Profile,
    StockTrade,
    TradeSide,
)
from core.services.imports.brokers import (
    BrokerFormatError,
    NormalizedCA,
    NormalizedDividend,
    NormalizedTrade,
    get_adapter,
)
from core.services.imports.generic import ImportResult

_SOURCE_MAP = {
    "zerodha": DividendSource.ZERODHA_XLSX,
    "chola": DividendSource.CHOLA_PDF,
    "aionion": DividendSource.AIONION_XLSX,
}


def _read_bytes(file: Any) -> bytes:
    """Accept Django UploadedFile, bytes, or already-opened file-like."""
    if isinstance(file, bytes | bytearray):
        return bytes(file)
    if hasattr(file, "read"):
        data = file.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        return data
    raise TypeError(f"Cannot read bytes from {type(file).__name__}")


def _record_job(
    profile: Profile,
    *,
    scope: str,
    source: str,
    filename: str,
    status: str,
    rows_imported: int,
    log: str,
    mode: str = "append",
) -> ImportJob:
    return ImportJob.objects.create(
        profile=profile,
        source=source,
        scope=scope,
        mode=mode,
        filename=filename,
        rows_imported=rows_imported,
        status=status,
        log=log,
    )


def _get_or_create_broker_account(
    profile: Profile, broker_key: str, account_label: str
) -> BrokerAccount:
    """Resolve the BrokerAccount row.

    The import view auto-extracts the broker's client ID from each file
    and passes it as ``account_label``. We persist the same value into
    ``client_code`` so the canonical, broker-issued identifier is
    available alongside the display label.
    """
    ba, created = BrokerAccount.objects.get_or_create(
        profile=profile,
        broker_key=broker_key,
        account_label=account_label,
    )
    if created and not ba.client_code:
        ba.client_code = account_label
        ba.save(update_fields=["client_code"])
    return ba


def _get_or_create_instrument(
    profile: Profile,
    *,
    isin: str,
    symbol: str,
    name: str,
    kind: str,
) -> Instrument | None:
    """Resolve an Instrument row across the three identifiers a broker can
    supply: primary ISIN, an aliased ISIN, or just the exchange symbol.

    Lookup order:

    1. ``(profile, isin)`` exact match on the primary ISIN field.
    2. ``isin`` appears in another row's ``isin_aliases`` -- this is how
       corporate-action ISIN drift (face-value change, demerger) stays a
       single row across brokers that report the legacy vs. the post-CA
       ISIN.
    3. ``(profile, exchange_symbol, kind)`` -- catches no-ISIN imports
       (some Aionion XLSXs, OCR-only Chola rows) and any ISIN drift the
       alias list hasn't recorded yet. ``kind`` keeps a hypothetical
       same-symbol-different-asset-class collision from cross-matching.

    When step 2 or 3 matches and the new ``isin`` differs from the row's
    primary, we register the new ISIN as an alias rather than overwrite
    -- both ISINs are valid handles for the same security and future
    imports may use either.

    Returns ``None`` only when both ``isin`` and a usable symbol are blank.
    """
    # ``Instrument.exchange_symbol`` caps at 40 chars; brokers like Chola
    # ship long company names because they don't publish a separate ticker.
    # Treat any "symbol" > 40 chars as a name hint only and never persist
    # it into ``exchange_symbol``.
    short_symbol = symbol if len(symbol) <= 40 else ""
    effective_name = name or symbol or isin

    instrument: Instrument | None = None
    if isin:
        instrument = Instrument.objects.filter(profile=profile, isin=isin).first()
    if instrument is None and isin:
        # Alias lookup. JSONField __contains varies subtly across DB
        # backends; iterate in Python to keep behaviour identical on
        # SQLite + Postgres without a custom dialect-specific lookup.
        for cand in Instrument.objects.filter(profile=profile, kind=kind):
            if isin in (cand.isin_aliases or []):
                instrument = cand
                break
    if instrument is None and short_symbol:
        instrument = Instrument.objects.filter(
            profile=profile, exchange_symbol=short_symbol, kind=kind
        ).first()
    if instrument is None:
        if not isin and not short_symbol:
            return None
        instrument = Instrument.objects.create(
            profile=profile,
            isin=isin,
            exchange_symbol=short_symbol,
            name=effective_name,
            kind=kind,
        )
        return instrument

    # Enrich blanks without overwriting non-blank metadata. When a new
    # ISIN differs from the matched row's primary, register it as an
    # alias so the next import keyed on either ISIN resolves here.
    dirty = False
    if not instrument.isin and isin:
        instrument.isin = isin
        dirty = True
    elif isin and instrument.isin and instrument.isin != isin:
        aliases = list(instrument.isin_aliases or [])
        if isin not in aliases:
            aliases.append(isin)
            instrument.isin_aliases = aliases
            dirty = True
    if not instrument.exchange_symbol and short_symbol:
        instrument.exchange_symbol = short_symbol
        dirty = True
    if instrument.name in ("", instrument.isin, instrument.exchange_symbol) and name:
        instrument.name = name
        dirty = True
    if dirty:
        instrument.save()
    return instrument


def _upsert_trade(
    profile: Profile,
    broker_account: BrokerAccount,
    instrument: Instrument,
    norm: NormalizedTrade,
    import_job: ImportJob | None = None,
) -> bool:
    """Return True when a new row was created, False when it already existed."""

    defaults = {
        "profile": profile,
        "instrument": instrument,
        "trade_date": norm.trade_date,
        "exec_time": norm.exec_time,
        "side": TradeSide.BUY if norm.side == "BUY" else TradeSide.SELL,
        "quantity": norm.quantity,
        "price": norm.price,
        "brokerage": norm.brokerage,
        "stt": norm.stt,
        "gst": norm.gst,
        "stamp_duty": norm.stamp_duty,
        "sebi_charges": norm.sebi_charges,
        "exchange_charges": norm.exchange_charges,
        "total_charges": norm.total_charges,
        "net_amount": norm.net_amount,
        "currency": norm.currency,
        "off_market": norm.off_market,
        "raw_row_json": norm.raw,
        "import_job": import_job,
    }
    _, created = StockTrade.objects.get_or_create(
        broker_account=broker_account,
        trade_ref=norm.trade_ref,
        defaults=defaults,
    )
    return created


def _upsert_corporate_action(
    profile: Profile,
    broker_account: BrokerAccount,
    instrument: Instrument,
    norm: NormalizedCA,
) -> bool:
    """Create or no-op a ``CorporateAction`` row.

    Uniqueness is ``(broker_account, instrument, action_type, ex_date)`` so
    if the same ISIN is held in multiple demats and each broker's statement
    reports the same SPLIT/BONUS, we keep one row per broker -- the
    ``units_added`` field is per-account, so collapsing them globally would
    lose information.
    """

    defaults = {
        "profile": profile,
        "ratio_numerator": norm.ratio_numerator,
        "ratio_denominator": norm.ratio_denominator,
        "units_added": norm.units_added,
        "cash_component": norm.cash_component,
        "notes": "",
        "source": norm.broker_key,
    }
    _, created = CorporateAction.objects.get_or_create(
        broker_account=broker_account,
        instrument=instrument,
        action_type=norm.action_type,
        ex_date=norm.ex_date,
        defaults=defaults,
    )
    return created


def _upsert_dividend(
    profile: Profile,
    broker_account: BrokerAccount,
    instrument: Instrument,
    norm: NormalizedDividend,
    source: DividendSource,
    import_job: ImportJob | None = None,
) -> bool:
    defaults = {
        "pay_date": norm.pay_date,
        "tds": norm.tds,
        "dividend_per_share": norm.dividend_per_share,
        "quantity": norm.quantity,
        "currency": norm.currency,
        "source": source,
        "raw_row_json": norm.raw,
        "import_job": import_job,
    }
    _, created = DividendRecord.objects.get_or_create(
        profile=profile,
        broker_account=broker_account,
        instrument=instrument,
        ex_date=norm.ex_date,
        amount_gross=norm.amount_gross or norm.amount_net,
        defaults={**defaults, "amount_net": norm.amount_net},
    )
    return created


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def import_tradebook(
    profile: Profile,
    *,
    broker_key: str,
    account_label: str,
    file: Any,
    filename: str = "tradebook",
) -> ImportResult:
    """Ingest a broker tradebook file into ``StockTrade`` rows."""

    adapter = get_adapter(broker_key)
    file_bytes = _read_bytes(file)

    inserted = 0
    skipped = 0
    errors: list[str] = []

    try:
        normalized = list(adapter.parse_tradebook(file_bytes, account_label=account_label))
    except BrokerFormatError as exc:
        job = _record_job(
            profile,
            scope="tradebook",
            source=broker_key,
            filename=filename,
            status=ImportStatus.ERROR,
            rows_imported=0,
            log=f"Parse failed: {exc}",
        )
        return ImportResult(job=job, errors=[str(exc)])

    with db_tx.atomic():
        broker_account = _get_or_create_broker_account(profile, broker_key, account_label)
        job = _record_job(
            profile,
            scope="tradebook",
            source=broker_key,
            filename=filename,
            status=ImportStatus.RUNNING,
            rows_imported=0,
            log="",
        )
        for norm in normalized:
            try:
                instrument = _get_or_create_instrument(
                    profile,
                    isin=norm.isin,
                    symbol=norm.symbol,
                    name=norm.name,
                    kind=getattr(norm, "instrument_kind", None) or InstrumentKind.STOCK,
                )
                if instrument is None:
                    skipped += 1
                    errors.append(f"{norm.symbol}: no ISIN and no symbol; row skipped")
                    continue
                created = _upsert_trade(profile, broker_account, instrument, norm, import_job=job)
                if created:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001 — keep importing other rows
                skipped += 1
                errors.append(f"{norm.symbol} {norm.trade_date}: {exc}")

        job.rows_imported = inserted
        status_ok = inserted > 0 or not errors
        job.status = ImportStatus.OK if status_ok else ImportStatus.ERROR
        log_lines = [f"inserted={inserted} skipped={skipped}"]
        if errors:
            log_lines.extend(errors[:50])
            if len(errors) > 50:
                log_lines.append(f"...and {len(errors) - 50} more")
        job.log = "\n".join(log_lines)
        job.save()

    return ImportResult(job=job, inserted=inserted, updated=0, skipped=skipped, errors=errors)


def import_dividends(
    profile: Profile,
    *,
    broker_key: str,
    account_label: str,
    file: Any,
    filename: str = "dividends",
) -> ImportResult:
    """Ingest a broker dividend statement into ``DividendRecord`` rows."""

    adapter = get_adapter(broker_key)
    file_bytes = _read_bytes(file)

    inserted = 0
    skipped = 0
    errors: list[str] = []

    try:
        normalized = list(adapter.parse_dividends(file_bytes, account_label=account_label))
    except BrokerFormatError as exc:
        job = _record_job(
            profile,
            scope="dividends",
            source=broker_key,
            filename=filename,
            status=ImportStatus.ERROR,
            rows_imported=0,
            log=f"Parse failed: {exc}",
        )
        return ImportResult(job=job, errors=[str(exc)])

    source = _SOURCE_MAP[broker_key]
    with db_tx.atomic():
        broker_account = _get_or_create_broker_account(profile, broker_key, account_label)
        job = _record_job(
            profile,
            scope="dividends",
            source=broker_key,
            filename=filename,
            status=ImportStatus.RUNNING,
            rows_imported=0,
            log="",
        )
        for norm in normalized:
            try:
                instrument = _get_or_create_instrument(
                    profile,
                    isin=norm.isin,
                    symbol=norm.symbol,
                    name=norm.name or norm.symbol,
                    kind=InstrumentKind.STOCK,
                )
                if instrument is None:
                    skipped += 1
                    errors.append(f"{norm.symbol or norm.name}: no ISIN/symbol; row skipped")
                    continue
                created = _upsert_dividend(
                    profile,
                    broker_account,
                    instrument,
                    norm,
                    source=source,
                    import_job=job,
                )
                if created:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                errors.append(f"{norm.symbol} {norm.ex_date}: {exc}")

        job.rows_imported = inserted
        status_ok = inserted > 0 or not errors
        job.status = ImportStatus.OK if status_ok else ImportStatus.ERROR
        log_lines = [f"inserted={inserted} skipped={skipped}"]
        if errors:
            log_lines.extend(errors[:50])
            if len(errors) > 50:
                log_lines.append(f"...and {len(errors) - 50} more")
        job.log = "\n".join(log_lines)
        job.save()

    return ImportResult(job=job, inserted=inserted, updated=0, skipped=skipped, errors=errors)


# ---------------------------------------------------------------------------
# Unified statement import (for brokers that ship a single mixed-ledger file
# like Chola's TransactionReport.pdf).
# ---------------------------------------------------------------------------


def import_statement(
    profile: Profile,
    *,
    broker_key: str,
    account_label: str,
    file: Any,
    filename: str = "statement",
) -> ImportResult:
    """Run all three adapter parsers against the same file bytes.

    Designed for brokers like Chola whose PDF contains trades, dividends,
    and corporate actions in one ledger. Safe to call on single-purpose
    files too (e.g. a Zerodha tradebook): the parsers that don't match
    the format raise ``BrokerFormatError`` which we swallow silently and
    continue with whichever parsers did match.

    ``NotImplementedError`` (stub brokers like Aionion) propagates so the
    user sees a clear failure rather than a silently-empty import.
    """

    adapter = get_adapter(broker_key)
    file_bytes = _read_bytes(file)
    # Source is looked up lazily inside the dividend block so that stub
    # adapters (e.g. Aionion) raise ``NotImplementedError`` from their
    # parser before we touch ``_SOURCE_MAP`` -- a strict KeyError here
    # would mask the more useful "not implemented" signal.

    trade_inserted = div_inserted = ca_inserted = 0
    trade_skipped = div_skipped = ca_skipped = 0
    errors: list[str] = []

    with db_tx.atomic():
        broker_account = _get_or_create_broker_account(profile, broker_key, account_label)
        job = _record_job(
            profile,
            scope="statement",
            source=broker_key,
            filename=filename,
            status=ImportStatus.RUNNING,
            rows_imported=0,
            log="",
        )

        # --- Trades ----------------------------------------------------
        try:
            for norm in adapter.parse_tradebook(file_bytes, account_label=account_label):
                try:
                    instrument = _get_or_create_instrument(
                        profile,
                        isin=norm.isin,
                        symbol=norm.symbol,
                        name=norm.name,
                        kind=getattr(norm, "instrument_kind", None) or InstrumentKind.STOCK,
                    )
                    if instrument is None:
                        trade_skipped += 1
                        errors.append(f"trade {norm.symbol}: no isin/symbol")
                        continue
                    if _upsert_trade(profile, broker_account, instrument, norm, import_job=job):
                        trade_inserted += 1
                    else:
                        trade_skipped += 1
                except Exception as exc:  # noqa: BLE001
                    trade_skipped += 1
                    errors.append(f"trade {norm.symbol} {norm.trade_date}: {exc}")
        except BrokerFormatError:
            pass

        # --- Dividends -------------------------------------------------
        source = _SOURCE_MAP[broker_key]
        try:
            for norm in adapter.parse_dividends(file_bytes, account_label=account_label):
                try:
                    instrument = _get_or_create_instrument(
                        profile,
                        isin=norm.isin,
                        symbol=norm.symbol,
                        name=norm.name or norm.symbol,
                        kind=InstrumentKind.STOCK,
                    )
                    if instrument is None:
                        div_skipped += 1
                        errors.append(f"dividend {norm.symbol or norm.name}: no isin/symbol")
                        continue
                    if _upsert_dividend(
                        profile,
                        broker_account,
                        instrument,
                        norm,
                        source=source,
                        import_job=job,
                    ):
                        div_inserted += 1
                    else:
                        div_skipped += 1
                except Exception as exc:  # noqa: BLE001
                    div_skipped += 1
                    errors.append(f"dividend {norm.symbol} {norm.ex_date}: {exc}")
        except BrokerFormatError:
            pass

        # --- Corporate actions -----------------------------------------
        try:
            for norm in adapter.parse_corporate_actions(file_bytes, account_label=account_label):
                try:
                    instrument = _get_or_create_instrument(
                        profile,
                        isin=norm.isin,
                        symbol=norm.symbol,
                        name=norm.name or norm.symbol,
                        kind=InstrumentKind.STOCK,
                    )
                    if instrument is None:
                        ca_skipped += 1
                        errors.append(f"corp_action {norm.symbol or norm.name}: no isin/symbol")
                        continue
                    if _upsert_corporate_action(profile, broker_account, instrument, norm):
                        ca_inserted += 1
                    else:
                        ca_skipped += 1
                except Exception as exc:  # noqa: BLE001
                    ca_skipped += 1
                    errors.append(f"corp_action {norm.symbol} {norm.ex_date}: {exc}")
        except BrokerFormatError:
            pass

        total_inserted = trade_inserted + div_inserted + ca_inserted
        total_skipped = trade_skipped + div_skipped + ca_skipped
        job.rows_imported = total_inserted
        status_ok = total_inserted > 0 or not errors
        job.status = ImportStatus.OK if status_ok else ImportStatus.ERROR
        log_lines = [
            f"trades: inserted={trade_inserted} skipped={trade_skipped}",
            f"dividends: inserted={div_inserted} skipped={div_skipped}",
            f"corporate_actions: inserted={ca_inserted} skipped={ca_skipped}",
        ]
        if errors:
            log_lines.extend(errors[:50])
            if len(errors) > 50:
                log_lines.append(f"...and {len(errors) - 50} more")
        job.log = "\n".join(log_lines)
        job.save()

    return ImportResult(
        job=job,
        inserted=total_inserted,
        updated=0,
        skipped=total_skipped,
        errors=errors,
    )

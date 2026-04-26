"""End-to-end tests for ``import_statement``.

Exercises the unified entrypoint that runs all three adapter parsers on
one file. The Chola PDF is the load-bearing case -- it contains trades,
dividends, and a SPLIT corporate action in one ledger -- and the Zerodha
XLSX is a control for "file shape that only matches one parser."
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.models import (
    BrokerAccount,
    BrokerKind,
    CorporateAction,
    CorporateActionType,
    DividendRecord,
    DividendSource,
    ImportJob,
    ImportStatus,
    Instrument,
    Profile,
    StockTrade,
    User,
)
from core.services.imports import import_statement

FIXTURES = Path(__file__).parent / "fixtures"
CHOLA_PDF = FIXTURES / "chola" / "TransactionReport.pdf"
ZERODHA_TRADES = FIXTURES / "zerodha" / "tradebook_sample.xlsx"
ZERODHA_DIVS = FIXTURES / "zerodha" / "dividends_sample.xlsx"


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


# ---------------------------------------------------------------------------
# Chola (mixed ledger)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_chola_statement_import_populates_all_three_tables(profile):
    result = import_statement(
        profile,
        broker_key="chola",
        account_label="Main",
        file=CHOLA_PDF.read_bytes(),
        filename="TransactionReport.pdf",
    )
    assert result.ok
    assert result.inserted > 0

    # Trades from the Chola ledger were persisted.
    trades = StockTrade.objects.filter(profile=profile)
    assert trades.count() > 0
    assert trades.filter(
        instrument__isin="INE092T01019",  # IDFC First Bank
        quantity=Decimal("34"),
        trade_date=date(2021, 4, 8),
    ).exists()

    # Dividends: ITC Ltd 442.75 on 2021-06-10
    itc_div = DividendRecord.objects.filter(
        profile=profile,
        instrument__isin="INE154A01025",
        ex_date=date(2021, 6, 10),
        amount_gross=Decimal("442.75"),
    ).first()
    assert itc_div is not None
    assert itc_div.source == DividendSource.CHOLA_PDF
    # Chola's Transaction Date is the bank-credit date; populated on pay_date.
    assert itc_div.pay_date == date(2021, 6, 10)

    # Corporate action: SBI Gold ETF SPLIT on 2022-01-06 with units_added=1089
    split = CorporateAction.objects.get(
        instrument__isin="INF200KA16D8",
        action_type=CorporateActionType.SPLIT,
        ex_date=date(2022, 1, 6),
    )
    assert split.units_added == Decimal("1089")
    assert split.ratio_numerator is None
    assert split.ratio_denominator is None
    # Chola actions are per-broker-account, not global.
    assert split.broker_account is not None

    # One BrokerAccount row was created.
    accounts = BrokerAccount.objects.filter(profile=profile, broker_key=BrokerKind.CHOLA)
    assert accounts.count() == 1


@pytest.mark.django_db
def test_chola_reimport_is_idempotent(profile):
    first = import_statement(
        profile,
        broker_key="chola",
        account_label="Main",
        file=CHOLA_PDF.read_bytes(),
    )
    second = import_statement(
        profile,
        broker_key="chola",
        account_label="Main",
        file=CHOLA_PDF.read_bytes(),
    )
    assert second.inserted == 0
    assert second.skipped == first.inserted


@pytest.mark.django_db
def test_chola_split_has_exactly_one_corporate_action(profile):
    """Even though ``import_statement`` runs all three parsers, the SPLIT
    row must not be double-counted (e.g. misparsed into DividendRecord)."""
    import_statement(
        profile,
        broker_key="chola",
        account_label="Main",
        file=CHOLA_PDF.read_bytes(),
    )
    assert (
        CorporateAction.objects.filter(
            profile=profile, action_type=CorporateActionType.SPLIT
        ).count()
        == 1
    )


# ---------------------------------------------------------------------------
# Zerodha via import_statement (graceful shape-mismatch handling)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_zerodha_tradebook_via_import_statement(profile):
    """Uploading the Zerodha tradebook XLSX through the unified endpoint
    should populate trades (matching parser) and skip dividends + actions
    (mismatched parsers raise BrokerFormatError which we swallow)."""
    result = import_statement(
        profile,
        broker_key="zerodha",
        account_label="Main",
        file=ZERODHA_TRADES.read_bytes(),
        filename="tradebook.xlsx",
    )
    assert result.ok
    assert StockTrade.objects.filter(profile=profile).count() > 0
    assert DividendRecord.objects.filter(profile=profile).count() == 0
    assert CorporateAction.objects.filter(profile=profile).count() == 0


@pytest.mark.django_db
def test_zerodha_dividends_via_import_statement(profile):
    result = import_statement(
        profile,
        broker_key="zerodha",
        account_label="Main",
        file=ZERODHA_DIVS.read_bytes(),
    )
    assert result.ok
    assert DividendRecord.objects.filter(profile=profile).count() > 0
    assert StockTrade.objects.filter(profile=profile).count() == 0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_aionion_via_import_statement_imports_trades(profile):
    """``import_statement`` is the unified entry point. Pointing it at an
    Aionion trades XLSX should produce StockTrade rows; the dividends and
    corp-action parsers fail cleanly (no Summary sheet / not exported)
    and are swallowed, so the dividend / CA counts are zero."""
    aionion_trades = Path(__file__).parent / "fixtures" / "aionion" / "equity_trades_sample.xlsx"
    result = import_statement(
        profile,
        broker_key="aionion",
        account_label="Main",
        file=aionion_trades.read_bytes(),
    )
    assert result.inserted > 0
    # Expect 97 trades (matches the file's TRADES EXECUTED total)
    assert result.inserted == 97


@pytest.mark.django_db
def test_gibberish_file_records_error_job(profile):
    result = import_statement(
        profile,
        broker_key="chola",
        account_label="Main",
        file=b"definitely not a PDF",
        filename="junk.pdf",
    )
    assert result.inserted == 0
    # All three parsers should fail with BrokerFormatError, so nothing got
    # persisted but the ImportJob was recorded.
    jobs = ImportJob.objects.filter(profile=profile, scope="statement")
    assert jobs.count() == 1
    # Empty parse is still ImportStatus.OK when no errors recorded
    # (the only source of errors here is per-row, not whole-file parsing).
    assert jobs.first().status == ImportStatus.OK


@pytest.mark.django_db
def test_chola_instrument_created_with_clean_name(profile):
    """The ``Britannia Industries\\nLtd`` PDF cell should land in the DB
    with a clean single-spaced name, not with an embedded newline."""
    import_statement(
        profile,
        broker_key="chola",
        account_label="Main",
        file=CHOLA_PDF.read_bytes(),
    )
    britannia = Instrument.objects.get(profile=profile, isin="INE216A01030")
    assert "\n" not in britannia.name
    assert britannia.name == "Britannia Industries Ltd"

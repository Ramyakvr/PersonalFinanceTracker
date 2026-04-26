"""Price service tests: latest_price lookup, refresh flow, fetchers.

Fetchers are tested with injected loaders so nothing touches the network.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.models import (
    Asset,
    AssetCategory,
    Instrument,
    InstrumentKind,
    PriceSource,
    PriceTick,
    Profile,
    User,
    UserPreferences,
)
from core.services.prices import (
    latest_price,
    refresh_prices,
    refresh_prices_all,
    upsert_tick,
)
from core.services.prices_fetchers.amfi import fetch_mf_navs, parse_navall
from core.services.prices_fetchers.nse import fetch_equity_prices, parse_bhavcopy


@pytest.fixture
def profile(db):
    user = User.objects.create(username="self", base_currency="INR")
    return Profile.objects.create(user=user, name="Self", is_default=True)


@pytest.fixture
def hdfc_bank(db, profile):
    return Instrument.objects.create(
        profile=profile,
        isin="INE040A01034",
        exchange_symbol="HDFCBANK",
        name="HDFC Bank",
        kind=InstrumentKind.STOCK,
    )


@pytest.fixture
def parag_fund(db, profile):
    return Instrument.objects.create(
        profile=profile,
        isin="INF879O01019",
        name="Parag Parikh Flexi Cap",
        kind=InstrumentKind.MF,
        amfi_code="122639",
    )


# ---------------------------------------------------------------------------
# latest_price
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_latest_price_returns_none_when_no_data(profile, hdfc_bank):
    price, stale = latest_price(hdfc_bank)
    assert price is None
    assert stale is True


@pytest.mark.django_db
def test_latest_price_uses_newest_tick(profile, hdfc_bank):
    upsert_tick(
        hdfc_bank,
        price=Decimal("800.0"),
        source=PriceSource.NSE_BHAVCOPY,
        as_of=date(2024, 1, 5),
    )
    upsert_tick(
        hdfc_bank,
        price=Decimal("820.0"),
        source=PriceSource.NSE_BHAVCOPY,
        as_of=date(2024, 1, 10),
    )

    price, stale = latest_price(hdfc_bank, as_of=date(2024, 1, 11))
    assert price == Decimal("820.0")
    # 1 business day gap (Wed 10th -> Thu 11th) -> fresh.
    assert stale is False


@pytest.mark.django_db
def test_latest_price_stale_after_many_business_days(profile, hdfc_bank):
    upsert_tick(
        hdfc_bank,
        price=Decimal("800.0"),
        source=PriceSource.NSE_BHAVCOPY,
        as_of=date(2024, 1, 1),
    )
    # 5 business days later.
    _, stale = latest_price(hdfc_bank, as_of=date(2024, 1, 10))
    assert stale is True


@pytest.mark.django_db
def test_latest_price_asset_fallback(profile, hdfc_bank):
    """When no PriceTick exists but an Asset linked to this Instrument has
    current_value + quantity, imply a per-unit price and flag stale."""

    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("12000"),
        quantity=Decimal("15"),
        instrument=hdfc_bank,
    )
    price, stale = latest_price(hdfc_bank)
    assert price == Decimal("800")
    assert stale is True  # asset-basis fallback is always stale


@pytest.mark.django_db
def test_latest_price_tick_beats_asset_fallback(profile, hdfc_bank):
    Asset.objects.create(
        profile=profile,
        category=AssetCategory.EQUITY,
        subtype="DIRECT_STOCK",
        name="HDFC Bank",
        currency="INR",
        current_value=Decimal("12000"),
        quantity=Decimal("15"),
        instrument=hdfc_bank,
    )
    upsert_tick(
        hdfc_bank,
        price=Decimal("900"),
        source=PriceSource.NSE_BHAVCOPY,
        as_of=date.today(),
    )
    price, stale = latest_price(hdfc_bank)
    assert price == Decimal("900")
    assert stale is False


@pytest.mark.django_db
def test_upsert_tick_overwrites_same_key(profile, hdfc_bank):
    d = date(2024, 1, 10)
    upsert_tick(hdfc_bank, price=Decimal("800"), source=PriceSource.NSE_BHAVCOPY, as_of=d)
    upsert_tick(hdfc_bank, price=Decimal("805"), source=PriceSource.NSE_BHAVCOPY, as_of=d)
    assert PriceTick.objects.filter(instrument=hdfc_bank).count() == 1
    assert PriceTick.objects.get(instrument=hdfc_bank).price == Decimal("805")


# ---------------------------------------------------------------------------
# refresh_prices
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_refresh_prices_noop_when_opt_out(profile, hdfc_bank):
    """Default: ``live_price_enabled`` is False -> refresh is a no-op."""
    result = refresh_prices(profile)
    assert result.ticks_written == 0
    assert PriceTick.objects.count() == 0


@pytest.mark.django_db
def test_refresh_prices_force_bypasses_opt_out(profile, hdfc_bank):
    """Manual "Refresh now" button passes ``force=True`` so the user can
    fetch even without the persistent opt-in."""

    def fake_nse(_instruments):
        return [(hdfc_bank, Decimal("850.00"), "INR", date(2024, 1, 10))]

    def fake_amfi(_instruments):
        return []

    result = refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        force=True,
    )
    assert result.ticks_written == 1
    tick = PriceTick.objects.get(instrument=hdfc_bank)
    assert tick.price == Decimal("850.00")
    assert tick.source == PriceSource.NSE_BHAVCOPY


@pytest.mark.django_db
def test_refresh_prices_honours_enabled_flag(profile, hdfc_bank):
    UserPreferences.objects.create(user=profile.user, live_price_enabled=True)

    def fake_nse(_instruments):
        return [(hdfc_bank, Decimal("100"), "INR", date(2024, 1, 1))]

    def fake_amfi(_instruments):
        return []

    result = refresh_prices(profile, equity_fetcher=fake_nse, mf_fetcher=fake_amfi)
    assert result.ticks_written == 1


@pytest.mark.django_db
def test_refresh_prices_records_last_refresh_at(profile, hdfc_bank):
    def noop(_):
        return []

    refresh_prices(profile, equity_fetcher=noop, mf_fetcher=noop, force=True)
    prefs = UserPreferences.objects.get(user=profile.user)
    assert prefs.last_price_refresh_at is not None


@pytest.mark.django_db
def test_refresh_prices_writes_mf_navs(profile, parag_fund):
    def fake_amfi(_instruments):
        return [(parag_fund, Decimal("55.42"), "INR", date(2024, 1, 10))]

    def noop(_):
        return []

    result = refresh_prices(profile, equity_fetcher=noop, mf_fetcher=fake_amfi, force=True)
    assert result.ticks_written == 1
    tick = PriceTick.objects.get(instrument=parag_fund)
    assert tick.price == Decimal("55.42")
    assert tick.source == PriceSource.AMFI


@pytest.mark.django_db
def test_refresh_prices_accumulates_errors_without_crashing(profile, hdfc_bank):
    def broken(_instruments):
        raise RuntimeError("network went splat")

    def noop(_):
        return []

    result = refresh_prices(profile, equity_fetcher=broken, mf_fetcher=noop, force=True)
    assert result.ticks_written == 0
    assert any("network went splat" in e for e in result.errors)


@pytest.mark.django_db
def test_refresh_prices_all_iterates_opted_in_profiles(db):
    u1 = User.objects.create(username="a", base_currency="INR")
    u2 = User.objects.create(username="b", base_currency="INR")
    p1 = Profile.objects.create(user=u1, name="p1", is_default=True)
    p2 = Profile.objects.create(user=u2, name="p2", is_default=True)
    UserPreferences.objects.create(user=u1, live_price_enabled=True)
    UserPreferences.objects.create(user=u2, live_price_enabled=False)
    Instrument.objects.create(
        profile=p1,
        isin="INE040A01034",
        exchange_symbol="HDFCBANK",
        name="HDFC Bank",
        kind=InstrumentKind.STOCK,
    )
    Instrument.objects.create(
        profile=p2,
        isin="INE002A01018",
        exchange_symbol="RELIANCE",
        name="Reliance",
        kind=InstrumentKind.STOCK,
    )

    # Patch the fetchers on the module to keep the test offline.
    from core.services import prices as prices_module

    orig = prices_module.refresh_prices

    def stub(profile, *, force=False, **kwargs):
        # Only `p1` is opted in; simulate one successful tick for p1.
        from core.models import PriceTick as _PT

        if not _opt_in(profile):
            return prices_module.RefreshResult()
        instr = Instrument.objects.filter(profile=profile).first()
        if instr:
            _PT.objects.update_or_create(
                instrument=instr,
                source="nse_bhavcopy",
                as_of=date(2024, 1, 1),
                defaults={"price": Decimal("1"), "currency": "INR"},
            )
            return prices_module.RefreshResult(ticks_written=1, instruments_scanned=1)
        return prices_module.RefreshResult()

    def _opt_in(p):
        prefs = UserPreferences.objects.filter(user=p.user).first()
        return bool(prefs and prefs.live_price_enabled)

    prices_module.refresh_prices = stub
    try:
        summary = refresh_prices_all()
    finally:
        prices_module.refresh_prices = orig

    assert summary["profiles"] == 1
    assert summary["ticks_written"] == 1


# ---------------------------------------------------------------------------
# NSE fetcher (offline, injected loader)
# ---------------------------------------------------------------------------


NSE_SAMPLE = """SYMBOL, SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER
HDFCBANK,EQ,10-Jan-2024,800.00,801.00,810.00,798.00,808.50,809.75,805.20,123456,9876.54,2100,100000,81.00
RELIANCE,EQ,10-Jan-2024,2300.00,2310.00,2350.00,2295.00,2342.50,2345.00,2320.80,543210,126543.00,8700,450000,82.88
NIFTYBEES,ST,10-Jan-2024,250.00,251.00,252.50,249.75,252.00,251.90,251.00,1000000,2510.00,500,900000,90.00
TATAMOTORS,BE,10-Jan-2024,500.00,505.00,510.00,498.00,506.00,505.50,505.00,200000,1010.00,1500,180000,90.00
INDEX500,XZ,10-Jan-2024,0.00,0.00,0.00,0.00,0.00,0.00,0.00,0,0.00,0,0,0.00
"""


def test_parse_bhavcopy_filters_to_tradeable_series():
    prices = parse_bhavcopy(NSE_SAMPLE.encode("utf-8"))
    assert "HDFCBANK" in prices
    assert "RELIANCE" in prices
    # NIFTYBEES (ST) and TATAMOTORS (BE) are tradeable equity series.
    assert "NIFTYBEES" in prices
    assert "TATAMOTORS" in prices
    # The junk XZ series must be filtered.
    assert "INDEX500" not in prices


def test_parse_bhavcopy_close_price_matches_sample():
    prices = parse_bhavcopy(NSE_SAMPLE.encode("utf-8"))
    price, as_of = prices["HDFCBANK"]
    assert price == Decimal("809.75")
    assert as_of == date(2024, 1, 10)


@pytest.mark.django_db
def test_fetch_equity_prices_walks_back_on_holiday(profile, hdfc_bank):
    """When today's bhavcopy is missing (weekend / holiday), the fetcher
    walks back up to a week and uses the first available day."""

    calls: list[date] = []

    def loader(d):
        calls.append(d)
        if d == date(2024, 1, 10):
            return NSE_SAMPLE.encode("utf-8")
        return None

    rows = fetch_equity_prices([hdfc_bank], loader=loader, today=date(2024, 1, 12))
    assert len(rows) == 1
    inst, price, ccy, as_of = rows[0]
    assert inst == hdfc_bank
    assert price == Decimal("809.75")
    assert ccy == "INR"
    assert as_of == date(2024, 1, 10)
    assert date(2024, 1, 12) in calls  # tried today first


@pytest.mark.django_db
def test_fetch_equity_prices_empty_without_loader_data(profile, hdfc_bank):
    rows = fetch_equity_prices([hdfc_bank], loader=lambda _: None)
    assert rows == []


@pytest.mark.django_db
def test_fetch_equity_prices_ignores_non_equity(profile, parag_fund):
    """MF and bond instruments shouldn't be looked up in the bhavcopy."""
    rows = fetch_equity_prices(
        [parag_fund],
        loader=lambda _: NSE_SAMPLE.encode("utf-8"),
        today=date(2024, 1, 10),
    )
    # parag_fund has no exchange_symbol -> no match in the SYMBOL-keyed bhavcopy.
    assert rows == []


# ---------------------------------------------------------------------------
# AMFI fetcher
# ---------------------------------------------------------------------------


AMFI_SAMPLE = """Open Ended Schemes ( Equity Scheme - Multi Cap Fund )

Parag Parikh Financial Advisory Services Ltd
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
122639;INF879O01019;INF879O01027;Parag Parikh Flexi Cap Fund - Direct Plan - Growth;  55.4200;10-Jan-2024
100123;INF000000001;-;Suspicious Fund;N.A.;10-Jan-2024
100456;-;-;Empty Row Fund;;10-Jan-2024
"""


def test_parse_navall_skips_non_data_lines():
    idx = parse_navall(AMFI_SAMPLE)
    assert "INF879O01019" in idx
    assert "INF879O01027" in idx
    assert "122639" in idx
    # N.A. row excluded.
    assert "INF000000001" not in idx
    # Empty NAV excluded.
    assert "100456" not in idx


def test_parse_navall_record_values():
    idx = parse_navall(AMFI_SAMPLE)
    nav, as_of, code = idx["INF879O01019"]
    assert nav == Decimal("55.4200")
    assert as_of == date(2024, 1, 10)
    assert code == "122639"


@pytest.mark.django_db
def test_fetch_mf_navs_uses_isin_then_amfi_code(profile, parag_fund):
    rows = fetch_mf_navs(
        [parag_fund],
        loader=lambda: AMFI_SAMPLE.encode("utf-8"),
    )
    assert len(rows) == 1
    inst, price, ccy, as_of = rows[0]
    assert inst == parag_fund
    assert price == Decimal("55.4200")
    assert ccy == "INR"
    assert as_of == date(2024, 1, 10)


@pytest.mark.django_db
def test_fetch_mf_navs_amfi_code_fallback(profile):
    """Instrument with no ISIN but an AMFI code should still resolve."""
    fund = Instrument.objects.create(
        profile=profile,
        isin="",
        name="AMFI-code-only Fund",
        kind=InstrumentKind.MF,
        amfi_code="122639",
    )
    rows = fetch_mf_navs([fund], loader=lambda: AMFI_SAMPLE.encode("utf-8"))
    assert len(rows) == 1
    assert rows[0][1] == Decimal("55.4200")


def test_fetch_mf_navs_empty_when_loader_returns_none():
    assert fetch_mf_navs([], loader=lambda: None) == []


# ---------------------------------------------------------------------------
# NSE master ISIN -> SYMBOL backfill (Chola pricing fix)
# ---------------------------------------------------------------------------


EQUITY_MASTER_SAMPLE = (
    b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
    b"ITC,ITC Limited,EQ,23-AUG-1995,1,1,INE154A01025,1\n"
    b"HCLTECH,HCL Technologies Limited,EQ,06-JAN-2000,2,1,INE860A01027,2\n"
)
ETF_MASTER_SAMPLE = (
    b"Symbol,Underlying,SecurityName,DateofListing,MarketLot,ISINNumber,FaceValue\n"
    b"GOLDBEES,Domestic Price of Gold,Gold BeES,08-Mar-07,1,INF204KB17I5,100\n"
)


def test_fetch_isin_to_symbol_merges_equity_and_etf():
    from core.services.prices_fetchers.nse_master import (
        EQUITY_MASTER_URL,
        ETF_MASTER_URL,
        fetch_isin_to_symbol,
    )

    def loader(url: str) -> bytes | None:
        if url == EQUITY_MASTER_URL:
            return EQUITY_MASTER_SAMPLE
        if url == ETF_MASTER_URL:
            return ETF_MASTER_SAMPLE
        return None

    out = fetch_isin_to_symbol(loader=loader)
    assert out["INE154A01025"] == "ITC"
    assert out["INE860A01027"] == "HCLTECH"
    assert out["INF204KB17I5"] == "GOLDBEES"


def test_parse_bhavcopy_includes_invit_and_reit_series():
    """SERIES = IV (InvITs like PGINVIT) and RR (REITs) must price the
    same way as EQ rows -- they're cash-segment securities a retail
    portfolio holds directly.
    """
    sample = (
        "SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
        "PGINVIT,IV,24-Apr-2026,93.25,93.40,93.43,92.80,93.00,93.00,93.03,1932167,1797.45,8268,1754498,90.80\n"
        "EMBASSY,RR,24-Apr-2026,432.00,432.50,433.10,430.00,432.97,432.97,432.50,123,55.00,80,80,65.00\n"
        "10YGS2034,GS,24-Apr-2026,99.00,99.10,99.30,99.00,99.20,99.20,99.15,500,49.50,5,500,100.00\n"
    )
    out = parse_bhavcopy(sample.encode("utf-8"))
    assert "PGINVIT" in out  # InvIT
    assert "EMBASSY" in out  # REIT
    assert "10YGS2034" not in out  # G-sec stays excluded


def test_fetch_isin_to_symbol_includes_trust_fallback():
    """When the master CSVs don't carry an InvIT / REIT ISIN, the
    ``TRUST_ISIN_TO_SYMBOL`` static map must still resolve it.
    """
    from core.services.prices_fetchers.nse_master import (
        TRUST_ISIN_TO_SYMBOL,
        fetch_isin_to_symbol,
    )

    out = fetch_isin_to_symbol(loader=lambda _url: None)
    # Every trust mapping is present even when both master endpoints fail.
    assert out["INE0HHJ23014"] == "PGINVIT"
    for isin, sym in TRUST_ISIN_TO_SYMBOL.items():
        assert out[isin] == sym


def test_fetch_isin_to_symbol_master_wins_over_trust_fallback():
    """If NSE later adds an InvIT to the equity master, the master entry
    must take precedence over the static map (so renames flow through).
    """
    from core.services.prices_fetchers.nse_master import (
        EQUITY_MASTER_URL,
        fetch_isin_to_symbol,
    )

    sample = (
        b"SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE\n"
        b"PGINVIT,PowerGrid Infrastructure Investment Trust,IV,24-APR-2021,100,1,INE0HHJ23014,100\n"
    )

    def loader(url: str) -> bytes | None:
        return sample if url == EQUITY_MASTER_URL else None

    out = fetch_isin_to_symbol(loader=loader)
    assert out["INE0HHJ23014"] == "PGINVIT"


def test_fetch_isin_to_symbol_survives_etf_outage():
    """When the ETF endpoint 404s, the equity map must still come back."""
    from core.services.prices_fetchers.nse_master import (
        EQUITY_MASTER_URL,
        ETF_MASTER_URL,
        fetch_isin_to_symbol,
    )

    def loader(url: str) -> bytes | None:
        if url == EQUITY_MASTER_URL:
            return EQUITY_MASTER_SAMPLE
        if url == ETF_MASTER_URL:
            return None  # transient failure
        return None

    out = fetch_isin_to_symbol(loader=loader)
    assert "INE154A01025" in out
    assert out["INE154A01025"] == "ITC"


@pytest.mark.django_db
def test_refresh_prices_backfills_chola_symbols_from_master(profile):
    """Chola PDFs ship ISIN + name but no ticker. The backfill step must
    populate ``exchange_symbol`` so the bhavcopy fetch can resolve them.
    """
    chola_itc = Instrument.objects.create(
        profile=profile,
        isin="INE154A01025",
        exchange_symbol="",  # Chola adapter leaves this blank
        name="ITC Ltd",
        kind=InstrumentKind.STOCK,
    )
    chola_hcl = Instrument.objects.create(
        profile=profile,
        isin="INE860A01027",
        exchange_symbol="",
        name="HCL Technologies Ltd",
        kind=InstrumentKind.STOCK,
    )

    captured_batch: list[Instrument] = []

    def fake_nse(instruments):
        captured_batch.extend(instruments)
        return [
            (i, Decimal("100"), "INR", date(2024, 1, 10))
            for i in instruments
        ]

    def fake_amfi(_):
        return []

    def stub_resolver():
        return {
            "INE154A01025": "ITC",
            "INE860A01027": "HCLTECH",
        }

    result = refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=stub_resolver,
        force=True,
    )
    assert result.ticks_written == 2
    chola_itc.refresh_from_db()
    chola_hcl.refresh_from_db()
    assert chola_itc.exchange_symbol == "ITC"
    assert chola_hcl.exchange_symbol == "HCLTECH"
    # Both backfilled rows must have made it into the equity batch.
    assert {i.id for i in captured_batch} == {chola_itc.id, chola_hcl.id}


@pytest.mark.django_db
def test_refresh_prices_skips_backfill_when_symbol_already_set(profile, hdfc_bank):
    """The resolver should not be invoked when no instrument needs it --
    avoids an unnecessary network round-trip on every refresh.
    """
    calls = {"count": 0}

    def stub_resolver():
        calls["count"] += 1
        return {}

    def fake_nse(_instruments):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=stub_resolver,
        force=True,
    )
    assert calls["count"] == 0


@pytest.mark.django_db
def test_refresh_prices_backfill_tolerates_unknown_isin(profile):
    """Instruments whose ISIN isn't in the NSE master are left untouched
    (e.g. unlisted, suspended, or non-NSE securities). Refresh proceeds
    for the rest."""
    unknown = Instrument.objects.create(
        profile=profile,
        isin="INXXXXXXXXXX",
        exchange_symbol="",
        name="Unknown Co",
        kind=InstrumentKind.STOCK,
    )

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=lambda: {"INE154A01025": "ITC"},
        force=True,
    )
    unknown.refresh_from_db()
    assert unknown.exchange_symbol == ""


@pytest.mark.django_db
def test_refresh_prices_backfill_repairs_company_name_leftovers(profile):
    """Older Chola imports planted the company name into
    ``exchange_symbol``. Those rows are no longer "blank" but the value
    is still useless for the bhavcopy lookup; backfill must replace them
    with the real ticker rather than leaving them broken forever.
    """
    inst = Instrument.objects.create(
        profile=profile,
        isin="INE154A01025",
        exchange_symbol="ITC Limited",  # name fragment, not a ticker
        name="ITC Ltd",
        kind=InstrumentKind.STOCK,
    )

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=lambda: {"INE154A01025": "ITC"},
        force=True,
    )
    inst.refresh_from_db()
    assert inst.exchange_symbol == "ITC"


@pytest.mark.django_db
def test_refresh_prices_backfill_preserves_real_tickers(profile):
    """A correctly-set ticker (uppercase, no spaces) is left alone --
    the heuristic must not nuke a legitimate symbol.
    """
    inst = Instrument.objects.create(
        profile=profile,
        isin="INE154A01025",
        exchange_symbol="ITC",  # real ticker
        name="ITC Ltd",
        kind=InstrumentKind.STOCK,
    )

    calls = {"n": 0}

    def stub_resolver():
        calls["n"] += 1
        return {"INE154A01025": "DIFFERENT"}  # would be wrong if applied

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=stub_resolver,
        force=True,
    )
    inst.refresh_from_db()
    assert inst.exchange_symbol == "ITC"
    assert calls["n"] == 0  # resolver never invoked when nothing needs fixing


@pytest.mark.django_db
def test_refresh_prices_backfills_pginvit_by_name_when_isin_mismatches(profile):
    """The user reported PGINVIT not pricing despite the trust ISIN
    being in our static map. Brokers occasionally carry a different ISIN
    for the same trust (re-issuance / scheme reorganisation). The name
    keyword fallback must catch those rows so they price regardless.
    """
    inst = Instrument.objects.create(
        profile=profile,
        isin="INE0HHJ23099",  # NOT in TRUST_ISIN_TO_SYMBOL
        exchange_symbol="",
        name="Powergrid Infrastructure Investment Trust",
        kind=InstrumentKind.STOCK,
    )

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=lambda: {},  # master returns nothing for this ISIN
        force=True,
    )
    inst.refresh_from_db()
    assert inst.exchange_symbol == "PGINVIT"


@pytest.mark.django_db
def test_refresh_prices_backfills_reit_by_name(profile):
    """Same fallback for REITs -- broker may use a non-master ISIN."""
    inst = Instrument.objects.create(
        profile=profile,
        isin="INXXXXXXXXXX",
        exchange_symbol="",
        name="Embassy Office Parks REIT",
        kind=InstrumentKind.STOCK,
    )

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=lambda: {},
        force=True,
    )
    inst.refresh_from_db()
    assert inst.exchange_symbol == "EMBASSY"


@pytest.mark.django_db
def test_refresh_prices_isin_resolution_wins_over_name(profile):
    """If the master returns a SYMBOL for the ISIN, that wins -- the
    name fallback is only consulted when ISIN resolution fails.
    """
    inst = Instrument.objects.create(
        profile=profile,
        isin="INE154A01025",
        exchange_symbol="",
        name="Powergrid Infrastructure Investment Trust",  # would match PGINVIT
        kind=InstrumentKind.STOCK,
    )

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=lambda: {"INE154A01025": "ITC"},
        force=True,
    )
    inst.refresh_from_db()
    assert inst.exchange_symbol == "ITC"


@pytest.mark.django_db
def test_refresh_prices_backfill_swallows_resolver_errors(profile):
    """A flaky NSE master endpoint must not break the refresh -- the
    fetcher pass should still run, just without backfilled symbols.
    """
    Instrument.objects.create(
        profile=profile,
        isin="INE154A01025",
        exchange_symbol="",
        name="ITC Ltd",
        kind=InstrumentKind.STOCK,
    )

    def boom():
        raise RuntimeError("master endpoint down")

    def fake_nse(_):
        return []

    def fake_amfi(_):
        return []

    result = refresh_prices(
        profile,
        equity_fetcher=fake_nse,
        mf_fetcher=fake_amfi,
        isin_resolver=boom,
        force=True,
    )
    assert result.errors == []  # backfill failure is swallowed silently

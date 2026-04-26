"""Price service: latest-known price lookup + refresh orchestration.

Reads come from the ``PriceTick`` table (populated by source-specific
fetchers in ``prices_fetchers/``) with a fallback to ``Asset.current_value``
when no tick exists yet. Writes go through ``upsert_tick`` which is
idempotent on ``(instrument, source, as_of)``.

**Privacy:** live-price fetch is off by default per CLAUDE.md §6. Users
opt in via ``UserPreferences.live_price_enabled``. The service respects
the flag -- ``refresh_prices`` is a no-op when the flag is off.

**Staleness:** ``latest_price`` returns ``(price, is_stale)``. A tick is
considered stale when it's older than 1 business day, or when we had to
fall back to the asset's cost basis (which is stale-by-construction).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from core.models import (
    Asset,
    Instrument,
    PriceSource,
    PriceTick,
    Profile,
    UserPreferences,
)

ZERO = Decimal(0)
STALE_AFTER_BUSINESS_DAYS = 1


def _business_days_between(a: date, b: date) -> int:
    """Rough count of business days between ``a`` and ``b`` (``a`` <= ``b``).

    Good enough for staleness -- we weight Mon-Fri as business days and
    don't attempt holiday calendars. A Saturday tick viewed on Monday
    should not read as "stale" just because two calendar days passed.
    """
    if a >= b:
        return 0
    count = 0
    cursor = a
    while cursor < b:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count


def latest_price(
    instrument: Instrument, as_of: date | None = None
) -> tuple[Decimal | None, bool]:
    """Return ``(price, is_stale)`` for ``instrument`` at ``as_of``.

    Lookup order:

    1. Latest ``PriceTick`` with ``as_of <= given_date`` (across all sources).
    2. Fallback to ``linked_asset.current_value / quantity`` when the asset
       links to this instrument and has both fields set.
    3. ``(None, True)`` when nothing is known.
    """
    as_of = as_of or timezone.localdate()

    tick = (
        PriceTick.objects.filter(instrument=instrument, as_of__lte=as_of)
        .order_by("-as_of")
        .first()
    )
    if tick is not None:
        stale = _business_days_between(tick.as_of, as_of) > STALE_AFTER_BUSINESS_DAYS
        return tick.price, stale

    # Asset fallback: any Asset linked to this instrument with a current value.
    asset = (
        Asset.objects.filter(instrument=instrument, quantity__gt=ZERO)
        .exclude(current_value__isnull=True)
        .order_by("-updated_at")
        .first()
    )
    if asset and asset.quantity and asset.quantity > ZERO:
        implied = Decimal(asset.current_value) / Decimal(asset.quantity)
        # Cost-basis fallback is always stale -- it's "what you paid", not
        # "what it's worth today".
        return implied, True

    return None, True


def upsert_tick(
    instrument: Instrument,
    *,
    price: Decimal,
    source: str,
    as_of: date,
    currency: str = "INR",
) -> PriceTick:
    """Insert a PriceTick or update the price on an existing one.

    Keyed by ``(instrument, source, as_of)``. Re-fetching the same source
    for the same date overwrites the price (brokers sometimes republish
    corrections).
    """
    tick, _ = PriceTick.objects.update_or_create(
        instrument=instrument,
        source=source,
        as_of=as_of,
        defaults={"price": price, "currency": currency},
    )
    return tick


# ---------------------------------------------------------------------------
# Refresh orchestration
# ---------------------------------------------------------------------------


@dataclass
class RefreshResult:
    ticks_written: int = 0
    instruments_scanned: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# Fetcher signature: ``(instruments) -> list[(instrument, price, currency, as_of)]``.
# Implementations live under ``core.services.prices_fetchers``.
Fetcher = Callable[
    [list[Instrument]],
    list[tuple[Instrument, Decimal, str, date]],
]

# Resolver signature for the ISIN -> SYMBOL backfill. Decoupled so tests
# can inject deterministic maps without hitting NSE's master lists.
IsinResolver = Callable[[], dict[str, str]]


def _live_price_enabled(profile: Profile) -> bool:
    prefs = UserPreferences.objects.filter(user=profile.user).first()
    return bool(prefs and prefs.live_price_enabled)


_NAME_HINTS = ("Ltd", "Limited", "Pvt", "Inc", "Co.", "Industries", "Bank")


def _looks_like_company_name(symbol: str) -> bool:
    """Detect ``exchange_symbol`` values that are obviously company-name
    leftovers from older Chola imports (the bug the
    ``normalize_instrument_symbols`` command was written to clean up).

    NSE tickers are uppercase letters/digits, ≤ 15 chars, no spaces, no
    lowercase. Anything that fails those rules is a name fragment.
    """
    if not symbol:
        return False
    if any(ch.isspace() for ch in symbol):
        return True
    if any(ch.islower() for ch in symbol):
        return True
    if any(hint in symbol for hint in _NAME_HINTS):
        return True
    return len(symbol) > 15


def _backfill_exchange_symbols(
    instruments: list[Instrument], resolver: IsinResolver
) -> int:
    """Populate ``exchange_symbol`` from the NSE master for STOCK rows
    where the field is blank or carries a company-name fragment from an
    older Chola import.

    Resolution order, per row:
      1. ISIN -> SYMBOL via the NSE equity + ETF master (and the static
         trust ISIN fallback merged into the resolver output).
      2. ``Instrument.name`` -> SYMBOL via the trust keyword fallback,
         for InvITs / REITs whose broker ISIN does not match the one
         our static map carries (the same trust has been issued under
         multiple ISINs across reissues; brokers don't always agree).

    Why this exists at all: Chola's PDF ledger does not carry exchange
    tickers, so every Chola-imported Instrument lands with
    ``exchange_symbol=""``. Without a ticker the bhavcopy fetcher
    silently skips them and prices never refresh.

    The "looks like a name" branch reuses the same heuristic as the
    ``normalize_instrument_symbols`` command -- without it, rows imported
    by older builds (which planted the company name into
    ``exchange_symbol``) would stay broken across refreshes since the
    field is no longer blank.

    Returns the number of instruments updated.
    """
    needs_backfill = [
        i for i in instruments
        if i.kind == "STOCK"
        and (i.isin or i.name)
        and (not i.exchange_symbol or _looks_like_company_name(i.exchange_symbol))
    ]
    if not needs_backfill:
        return 0
    try:
        isin_to_symbol = resolver() or {}
    except Exception:  # noqa: BLE001 -- master fetch is best-effort
        isin_to_symbol = {}

    # Lazy import: keep the heavy nse_master module out of the no-backfill
    # hot path.
    from core.services.prices_fetchers.nse_master import resolve_trust_by_name

    updated = 0
    for inst in needs_backfill:
        sym = ""
        if inst.isin:
            sym = isin_to_symbol.get(inst.isin.upper(), "")
        if not sym:
            sym = resolve_trust_by_name(inst.name)
        if not sym:
            continue
        inst.exchange_symbol = sym
        inst.save(update_fields=["exchange_symbol"])
        updated += 1
    return updated


def refresh_prices(
    profile: Profile,
    *,
    instruments: list[Instrument] | None = None,
    equity_fetcher: Fetcher | None = None,
    mf_fetcher: Fetcher | None = None,
    isin_resolver: IsinResolver | None = None,
    force: bool = False,
) -> RefreshResult:
    """Fetch fresh prices from NSE / AMFI for in-scope instruments.

    Respects the ``live_price_enabled`` preference (opt-in). Pass
    ``force=True`` to override -- used by a manual "Refresh now" button
    the user clicks deliberately.

    ``equity_fetcher``, ``mf_fetcher`` and ``isin_resolver`` default to
    the real NSE / AMFI implementations when omitted; tests inject
    in-memory stubs.
    """

    result = RefreshResult()
    if not force and not _live_price_enabled(profile):
        return result

    # Lazy import -- fetcher modules pull in optional deps (requests) that
    # we don't want to load when the feature is off.
    if equity_fetcher is None:
        from core.services.prices_fetchers.nse import fetch_equity_prices

        equity_fetcher = fetch_equity_prices
    if mf_fetcher is None:
        from core.services.prices_fetchers.amfi import fetch_mf_navs

        mf_fetcher = fetch_mf_navs
    if isin_resolver is None:
        from core.services.prices_fetchers.nse_master import fetch_isin_to_symbol

        isin_resolver = fetch_isin_to_symbol

    qs = instruments if instruments is not None else list(
        Instrument.objects.filter(profile=profile)
    )
    result.instruments_scanned = len(qs)

    # Backfill missing tickers from the NSE master before the bhavcopy
    # fetch; without this, Chola-imported stocks (no ticker in the PDF)
    # would be silently skipped on every refresh.
    _backfill_exchange_symbols(qs, isin_resolver)

    # NSE bhavcopy is keyed on SYMBOL, not ISIN -- so anything with an
    # ``exchange_symbol`` is fetchable even if the ISIN is blank (e.g. older
    # Chola PDFs that lacked ISIN extraction).
    equities = [i for i in qs if i.kind == "STOCK" and i.exchange_symbol]
    mfs = [i for i in qs if i.kind == "MF" and (i.isin or i.amfi_code)]

    for fetcher, batch, source in (
        (equity_fetcher, equities, PriceSource.NSE_BHAVCOPY),
        (mf_fetcher, mfs, PriceSource.AMFI),
    ):
        if not batch:
            continue
        try:
            for instrument, price, currency, as_of in fetcher(batch):
                upsert_tick(
                    instrument,
                    price=price,
                    source=source,
                    as_of=as_of,
                    currency=currency,
                )
                result.ticks_written += 1
        except Exception as exc:  # noqa: BLE001 — never crash the caller
            result.errors.append(f"{source}: {exc}")

    prefs, _ = UserPreferences.objects.get_or_create(user=profile.user)
    prefs.last_price_refresh_at = timezone.now()
    prefs.save(update_fields=["last_price_refresh_at"])
    return result


def refresh_prices_all() -> dict:
    """Run ``refresh_prices`` for every default profile whose user opted in.

    Intended entry point for the scheduled django-q task. Returns a dict
    summary suitable for logging.
    """
    summary = {"profiles": 0, "ticks_written": 0, "errors": []}
    for profile in Profile.objects.filter(is_default=True).select_related("user"):
        if not _live_price_enabled(profile):
            continue
        res = refresh_prices(profile, force=True)
        summary["profiles"] += 1
        summary["ticks_written"] += res.ticks_written
        summary["errors"].extend(res.errors)
    return summary

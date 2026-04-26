"""ISIN -> NSE SYMBOL resolver.

The NSE bhavcopy is keyed on SYMBOL (no ISIN column), so any Instrument
with a blank ``exchange_symbol`` cannot be priced through ``nse.py``.
Chola PDF imports always land here -- the broker's ledger never carries
an exchange ticker, only the company name + ISIN.

This module downloads the NSE equity & ETF master lists (which DO carry
both SYMBOL and ISIN) and returns an ``isin -> symbol`` map. The caller
(``prices.refresh_prices``) uses that map to backfill ``exchange_symbol``
on Instruments that have an ISIN but no symbol yet, so the next pass
through ``fetch_equity_prices`` resolves them against the bhavcopy.

Test-first: the public function takes an injectable ``loader`` so tests
feed deterministic CSV bytes without hitting the network.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable

EQUITY_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
ETF_MASTER_URL = "https://archives.nseindia.com/content/equities/eq_etfseclist.csv"

# NSE does not publish a public InvIT / REIT master CSV (the equivalents
# of EQUITY_L.csv / eq_etfseclist.csv 404). The bhavcopy carries the
# tickers under SERIES = IV (InvIT) and RR (REIT), but that file has no
# ISIN column, so we cannot bridge ISIN -> SYMBOL automatically for
# trusts. This static map is the manual fallback: extend it whenever a
# user holds an InvIT / REIT whose ISIN does not resolve via the master
# fetch. ``inspect_prices`` flags such instruments so the gap is
# visible.
#
# Best-effort ISINs sourced from public broker disclosures; if a
# brokerage uses a different ISIN for the same trust, the
# ``TRUST_NAME_TOKENS_TO_SYMBOL`` keyword map below catches the row
# regardless of which ISIN is on the Instrument.
TRUST_ISIN_TO_SYMBOL: dict[str, str] = {
    # InvITs (SERIES = IV)
    "INE0HHJ23014": "PGINVIT",   # PowerGrid Infrastructure Investment Trust
    "INE183Q01024": "IRBINVIT",  # IRB InvIT Fund
    "INE219X23014": "INDIGRID",  # India Grid Trust
    # REITs (SERIES = RR)
    "INE041025011": "EMBASSY",   # Embassy Office Parks REIT
    "INE0CCU25019": "MINDSPACE", # Mindspace Business Parks REIT
    "INE0FDU25010": "BIRET",     # Brookfield India REIT
    "INE0OS725019": "NXST",      # Nexus Select Trust
}

# Name-keyword fallback for trusts. Each entry is ``(required tokens,
# symbol)``: the row's ``Instrument.name`` (lowercased) must contain
# every token for the symbol to be picked. This bridges the case where
# the broker file's ISIN does not match the one cited in
# ``TRUST_ISIN_TO_SYMBOL`` (e.g. PowerGrid Infra Trust has been listed
# under multiple ISINs across reissues -- the broker may carry one and
# our static map another). Order matters: the first matching entry
# wins, so longer / more-specific tuples come first.
TRUST_NAME_TOKENS_TO_SYMBOL: tuple[tuple[tuple[str, ...], str], ...] = (
    (("powergrid", "infrastructure"), "PGINVIT"),
    (("power", "grid", "infrastructure"), "PGINVIT"),
    (("irb", "invit"), "IRBINVIT"),
    (("india", "grid", "trust"), "INDIGRID"),
    (("indigrid",), "INDIGRID"),
    (("embassy", "office", "parks"), "EMBASSY"),
    (("mindspace", "business", "parks"), "MINDSPACE"),
    (("brookfield", "india", "real"), "BIRET"),
    (("brookfield", "india", "reit"), "BIRET"),
    (("nexus", "select", "trust"), "NXST"),
)


def resolve_trust_by_name(name: str) -> str:
    """Return a trust SYMBOL when ``name`` matches one of the keyword
    tuples in ``TRUST_NAME_TOKENS_TO_SYMBOL``; otherwise ``""``.
    """
    if not name:
        return ""
    haystack = name.lower()
    for tokens, symbol in TRUST_NAME_TOKENS_TO_SYMBOL:
        if all(tok in haystack for tok in tokens):
            return symbol
    return ""

Loader = Callable[[str], bytes | None]


def _default_loader(url: str) -> bytes | None:
    """Fetch ``url`` with a User-Agent header. NSE rejects bare requests."""
    import urllib.error
    import urllib.request

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
        if exc.code in (403, 404):
            return None
        raise


def _parse(csv_bytes: bytes, *, isin_col_candidates: tuple[str, ...]) -> dict[str, str]:
    """Parse master CSV bytes -> {ISIN: SYMBOL}.

    NSE master CSVs ship with whitespace-padded headers (``" SERIES"``,
    ``" ISIN NUMBER"``). We normalise headers by stripping whitespace and
    accept a tuple of plausible ISIN column names because the equity and
    ETF lists disagree (``ISIN NUMBER`` vs ``ISINNumber``).
    """
    # The ETF master ships with stray non-UTF-8 bytes (typographic dashes
    # in some scheme names); equity master is clean UTF-8 with a BOM. Try
    # UTF-8 first, then fall back to latin-1 -- both share ASCII for the
    # SYMBOL/ISIN columns we actually read.
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    out: dict[str, str] = {}
    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        symbol = (row.get("SYMBOL") or row.get("Symbol") or "").upper()
        if not symbol:
            continue
        isin = ""
        for col in isin_col_candidates:
            if row.get(col):
                isin = row[col].upper()
                break
        if not isin:
            continue
        out[isin] = symbol
    return out


def fetch_isin_to_symbol(loader: Loader | None = None) -> dict[str, str]:
    """Return a merged ``{ISIN: SYMBOL}`` map across NSE equities + ETFs.

    Falls back to the curated ``TRUST_ISIN_TO_SYMBOL`` for InvITs / REITs,
    which NSE does not expose as a public master file.

    Best-effort: a missing/unreachable list is silently skipped, so a
    transient outage on the ETF endpoint does not wipe the equity map.
    Returns at minimum the trust fallback map even when both downloads
    fail.
    """
    if loader is None:
        loader = _default_loader

    out: dict[str, str] = {}

    eq_blob = loader(EQUITY_MASTER_URL)
    if eq_blob:
        out.update(_parse(eq_blob, isin_col_candidates=("ISIN NUMBER",)))

    etf_blob = loader(ETF_MASTER_URL)
    if etf_blob:
        # ETF master takes precedence for ISINs it covers (some equity
        # master listings predate ETF reclassification).
        out.update(_parse(etf_blob, isin_col_candidates=("ISINNumber", "ISIN")))

    # Trust fallback last: only fills ISINs the master files don't cover,
    # so a future NSE master expansion that adds InvITs would still win.
    for isin, symbol in TRUST_ISIN_TO_SYMBOL.items():
        out.setdefault(isin, symbol)

    return out

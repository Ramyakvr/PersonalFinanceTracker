"""AMFI NAV fetcher for Indian mutual funds.

AMFI publishes a single consolidated text file at
``https://www.amfiindia.com/spages/NAVAll.txt`` containing NAVs for
every Indian mutual fund scheme, updated every business day at ~22:00 IST.

Format (pipe-delimited)::

    Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Header / section separators interleave -- lines without 6 pipe-split
fields are skipped. We prefer to key on ISIN (growth plan first) so
brokers' imports dedupe correctly; Scheme Code is a secondary key.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from core.models import Instrument

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

Loader = Callable[[], bytes | None]


def _default_loader() -> bytes | None:
    import urllib.request

    req = urllib.request.Request(
        AMFI_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (personal-finance-tracker; local-first)",
            "Accept": "text/plain",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        return resp.read()


def parse_navall(text: str) -> dict[str, tuple[Decimal, date, str]]:
    """Parse NAVAll.txt -> {key: (nav, as_of, scheme_code)} where key can be ISIN or AMFI code.

    Each scheme may have two ISINs (growth + reinvestment); we index both
    to the same NAV so either will resolve.
    """

    out: dict[str, tuple[Decimal, date, str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ";" not in line:
            continue
        parts = line.split(";")
        if len(parts) < 6:
            continue
        scheme_code = parts[0].strip()
        isin_growth = parts[1].strip()
        isin_reinvest = parts[2].strip()
        nav_raw = parts[4].strip()
        date_raw = parts[5].strip()
        if not nav_raw or nav_raw.upper() in ("N.A.", "NA", "-"):
            continue
        try:
            nav = Decimal(nav_raw)
        except (InvalidOperation, ValueError):
            continue
        try:
            as_of = datetime.strptime(date_raw, "%d-%b-%Y").date()
        except ValueError:
            continue
        record = (nav, as_of, scheme_code)
        if scheme_code:
            out[scheme_code] = record
        if isin_growth and isin_growth != "-":
            out[isin_growth] = record
        if isin_reinvest and isin_reinvest != "-":
            out[isin_reinvest] = record
    return out


def fetch_mf_navs(
    instruments: list[Instrument],
    *,
    loader: Loader | None = None,
) -> list[tuple[Instrument, Decimal, str, date]]:
    if not instruments:
        return []
    if loader is None:
        loader = _default_loader
    blob = loader()
    if not blob:
        return []
    text = blob.decode("utf-8-sig", errors="replace")
    nav_index = parse_navall(text)
    if not nav_index:
        return []
    results: list[tuple[Instrument, Decimal, str, date]] = []
    for inst in instruments:
        # Prefer ISIN lookup (stable), then AMFI code, then aliases.
        record = None
        if inst.isin and inst.isin in nav_index:
            record = nav_index[inst.isin]
        elif inst.amfi_code and inst.amfi_code in nav_index:
            record = nav_index[inst.amfi_code]
        else:
            for alias in inst.isin_aliases or ():
                if alias in nav_index:
                    record = nav_index[alias]
                    break
        if record is None:
            continue
        nav, as_of, _ = record
        results.append((inst, nav, "INR", as_of))
    return results

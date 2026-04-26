"""XIRR (Extended Internal Rate of Return) solver.

Pure-Python Decimal implementation. Matches Excel's ``XIRR`` behaviour:

* Actual/365 day-count anchored at the earliest cash-flow date.
* Newton-Raphson first (fast when well-conditioned); bracketed bisection on
  ``[-0.99, 100]`` as a robust fallback.
* Returns ``None`` on degenerate inputs (``< 2`` non-zero flows, all same sign,
  all flows on a single date) instead of raising -- callers render a dash in
  that case.

Decimals only. No float. No ``numpy-financial``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

ZERO = Decimal(0)
ONE = Decimal(1)
DAYS_PER_YEAR = Decimal(365)

_STEP_TOL = Decimal("1e-7")
_NPV_TOL = Decimal("1e-6")
_MIN_RATE = Decimal("-0.999999")
_NEWTON_ITERS = 30
_BISECT_ITERS = 120
_BISECT_LO = Decimal("-0.99")
_BISECT_HI = Decimal("100")
_PREC = 40


def _prepare(flows: Iterable[tuple[date, Decimal]]) -> tuple[list[Decimal], list[Decimal]] | None:
    cleaned: list[tuple[date, Decimal]] = []
    for d, a in flows:
        dec = a if isinstance(a, Decimal) else Decimal(a)
        if dec != ZERO:
            cleaned.append((d, dec))
    if len(cleaned) < 2:
        return None
    if all(a > ZERO for _, a in cleaned) or all(a < ZERO for _, a in cleaned):
        return None
    if len({d for d, _ in cleaned}) < 2:
        return None
    t0 = min(d for d, _ in cleaned)
    years = [Decimal((d - t0).days) / DAYS_PER_YEAR for d, _ in cleaned]
    amounts = [a for _, a in cleaned]
    return years, amounts


def _npv(r: Decimal, years: list[Decimal], amounts: list[Decimal]) -> Decimal:
    base = ONE + r
    total = ZERO
    for t, a in zip(years, amounts, strict=True):
        total += a / (base**t)
    return total


def _dnpv(r: Decimal, years: list[Decimal], amounts: list[Decimal]) -> Decimal:
    base = ONE + r
    total = ZERO
    for t, a in zip(years, amounts, strict=True):
        total += -a * t / (base ** (t + ONE))
    return total


def xirr(
    flows: Iterable[tuple[date, Decimal]],
    guess: Decimal = Decimal("0.1"),
) -> Decimal | None:
    """Return the XIRR of ``flows`` as an annualised Decimal rate.

    ``flows`` is an iterable of ``(date, Decimal amount)`` pairs where outflows
    are negative and inflows positive. Flows on the same date may appear; they
    are summed by the discounting math naturally.
    """

    prepared = _prepare(flows)
    if prepared is None:
        return None
    years, amounts = prepared

    with localcontext() as ctx:
        ctx.prec = _PREC

        # --- Newton-Raphson ---
        r = Decimal(guess)
        for _ in range(_NEWTON_ITERS):
            if r <= _MIN_RATE:
                break
            try:
                f = _npv(r, years, amounts)
                if abs(f) < _NPV_TOL:
                    return +r  # normalise context
                fp = _dnpv(r, years, amounts)
            except (InvalidOperation, ZeroDivisionError):
                break
            if fp == ZERO:
                break
            try:
                step = f / fp
            except (InvalidOperation, ZeroDivisionError):
                break
            r_next = r - step
            if r_next <= _MIN_RATE:
                break
            if abs(step) < _STEP_TOL:
                return +r_next
            r = r_next

        # --- Bracketed bisection fallback ---
        lo, hi = _BISECT_LO, _BISECT_HI
        try:
            f_lo = _npv(lo, years, amounts)
            f_hi = _npv(hi, years, amounts)
        except (InvalidOperation, ZeroDivisionError):
            return None
        if f_lo == ZERO:
            return +lo
        if f_hi == ZERO:
            return +hi
        if f_lo * f_hi > ZERO:
            return None  # no sign change within bracket

        for _ in range(_BISECT_ITERS):
            mid = (lo + hi) / 2
            try:
                f_mid = _npv(mid, years, amounts)
            except (InvalidOperation, ZeroDivisionError):
                return None
            if abs(f_mid) < _NPV_TOL or (hi - lo) < _STEP_TOL:
                return +mid
            if f_mid * f_lo < ZERO:
                hi, f_hi = mid, f_mid
            else:
                lo, f_lo = mid, f_mid
        return +((lo + hi) / 2)

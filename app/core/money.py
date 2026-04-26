"""Cross-currency arithmetic. The only path for converting Decimal amounts between currencies.

Invariants:
- All money values are `Decimal`. Never `float`.
- Same-currency conversion is a pass-through.
- Missing rate raises `FxRateMissingError` — callers decide whether to fall back.
"""

from __future__ import annotations

from decimal import Decimal

from core.models import FxRate, User


class FxRateMissingError(Exception):
    """Raised when no FX rate is available for the requested pair."""


def to_base_currency(
    amount: Decimal,
    from_ccy: str,
    base_ccy: str,
    *,
    user: User,
) -> Decimal:
    if not isinstance(amount, Decimal):
        raise TypeError(f"amount must be Decimal, got {type(amount).__name__}")
    if from_ccy == base_ccy:
        return amount

    rate = (
        FxRate.objects.filter(user=user, from_ccy=from_ccy, to_ccy=base_ccy)
        .values_list("rate", flat=True)
        .first()
    )
    if rate is None:
        raise FxRateMissingError(f"No FX rate from {from_ccy} to {base_ccy}")
    return amount * rate


def format_money(amount: Decimal, ccy: str) -> str:
    """Human-readable money string. Rendering only — never for arithmetic."""
    symbols = {"INR": "\u20b9", "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}
    symbol = symbols.get(ccy, f"{ccy} ")
    quantized = amount.quantize(Decimal("0.01"))
    return f"{symbol}{quantized:,}"

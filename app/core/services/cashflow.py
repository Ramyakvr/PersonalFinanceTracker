"""Cashflow helpers: income vs expense for a date range. Base-currency only for simplicity.

Transactions in non-base currencies are currently skipped (matches the caveat in
`core.services.transactions.total_non_exempt`). Phase-4.1 can route them through FX.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from core.models import Profile, Transaction, TxType

ZERO = Decimal("0")


@dataclass
class Cashflow:
    income: Decimal
    expense: Decimal
    net: Decimal


def cashflow(
    profile: Profile, *, date_from: date, date_to: date, currency: str | None = None
) -> Cashflow:
    ccy = currency or profile.user.base_currency
    base_qs = Transaction.objects.filter(
        profile=profile,
        date__gte=date_from,
        date__lte=date_to,
        currency=ccy,
        category__is_exempt=False,
    )
    income = base_qs.filter(type=TxType.INCOME).aggregate(total=Sum("amount")).get("total") or ZERO
    expense = (
        base_qs.filter(type=TxType.EXPENSE).aggregate(total=Sum("amount")).get("total") or ZERO
    )
    return Cashflow(income=income, expense=expense, net=income - expense)

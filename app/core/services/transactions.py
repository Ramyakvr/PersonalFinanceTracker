"""Transaction CRUD + query helpers. Recurring is represented by a linked RecurringRule row."""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from django.db.models import Q, QuerySet, Sum

from core.models import Profile, RecurringRule, Tag, Transaction, TxType


def list_transactions(
    profile: Profile,
    *,
    tx_type: str,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    search: str = "",
    category_id: int | None = None,
) -> QuerySet[Transaction]:
    qs = (
        Transaction.objects.filter(profile=profile, type=tx_type)
        .select_related("category", "recurring_rule")
        .prefetch_related("tags")
    )
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    if search:
        qs = qs.filter(Q(description__icontains=search) | Q(notes__icontains=search))
    if category_id:
        qs = qs.filter(category_id=category_id)
    return qs.order_by("-date", "-id")


def total_non_exempt(qs: QuerySet[Transaction], *, currency: str) -> Decimal:
    """Sum amounts in `currency` across non-exempt categories.

    Different-currency rows are skipped. A Phase-4 helper will convert via FX.
    """
    total = (
        qs.filter(currency=currency, category__is_exempt=False)
        .aggregate(total=Sum("amount"))
        .get("total")
    )
    return total or Decimal("0")


def create_transaction(
    profile: Profile,
    *,
    tags: list[Tag] | None = None,
    is_recurring: bool = False,
    **fields,
) -> Transaction:
    recurring_rule = None
    if is_recurring:
        recurring_rule = RecurringRule.objects.create(
            profile=profile,
            template_json={
                "type": fields.get("type"),
                "category_id": fields["category"].id if fields.get("category") else None,
                "amount": str(fields.get("amount", "")),
                "currency": fields.get("currency", ""),
                "description": fields.get("description", ""),
            },
            cadence="monthly",
            start_date=fields["date"],
        )
    tx = Transaction.objects.create(profile=profile, recurring_rule=recurring_rule, **fields)
    if tags:
        tx.tags.set(tags)
    return tx


def update_transaction(
    tx: Transaction,
    *,
    tags: list[Tag] | None = None,
    is_recurring: bool = False,
    **fields,
) -> Transaction:
    for key, value in fields.items():
        setattr(tx, key, value)

    if is_recurring and tx.recurring_rule_id is None:
        tx.recurring_rule = RecurringRule.objects.create(
            profile=tx.profile,
            template_json={},
            cadence="monthly",
            start_date=tx.date,
        )
    elif not is_recurring and tx.recurring_rule_id is not None:
        old = tx.recurring_rule
        tx.recurring_rule = None
        tx.save()
        old.delete()

    tx.save()
    if tags is not None:
        tx.tags.set(tags)
    return tx


def delete_transaction(tx: Transaction) -> None:
    tx.delete()


def category_choices(profile: Profile, tx_type: str) -> list[tuple[int, str]]:
    """Return (id, name) pairs for categories matching the given type. System + profile."""
    from core.models import Category

    qs = Category.objects.filter(
        Q(profile=profile) | Q(profile__isnull=True), type=tx_type
    ).order_by("name")
    return [(c.id, c.name) for c in qs]


def type_for(url_segment: str) -> str:
    """Map url segment ("expenses" | "income") to a TxType value."""
    return TxType.INCOME if url_segment == "income" else TxType.EXPENSE

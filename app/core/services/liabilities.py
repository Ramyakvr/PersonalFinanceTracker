"""Liability CRUD + query helpers."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from core.models import Liability, Profile, Tag


def list_liabilities(
    profile: Profile,
    *,
    search: str = "",
    category: str = "",
    currency: str = "",
    tag_ids: list[int] | None = None,
) -> QuerySet[Liability]:
    qs = Liability.objects.filter(profile=profile).prefetch_related("tags")
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(notes__icontains=search))
    if category:
        qs = qs.filter(category=category)
    if currency:
        qs = qs.filter(currency=currency)
    if tag_ids:
        qs = qs.filter(tags__id__in=tag_ids).distinct()
    return qs.order_by("-updated_at")


def create_liability(profile: Profile, *, tags: list[Tag] | None = None, **fields) -> Liability:
    liability = Liability.objects.create(profile=profile, **fields)
    if tags:
        liability.tags.set(tags)
    return liability


def update_liability(liability: Liability, *, tags: list[Tag] | None = None, **fields) -> Liability:
    for key, value in fields.items():
        setattr(liability, key, value)
    liability.save()
    if tags is not None:
        liability.tags.set(tags)
    return liability


def delete_liability(liability: Liability) -> None:
    liability.delete()


def distinct_currencies(profile: Profile) -> list[str]:
    return list(
        Liability.objects.filter(profile=profile)
        .values_list("currency", flat=True)
        .distinct()
        .order_by("currency")
    )

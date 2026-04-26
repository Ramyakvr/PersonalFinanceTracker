"""Asset CRUD + query helpers. Views call these — views stay thin."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from core.models import Asset, Profile, Tag


def list_assets(
    profile: Profile,
    *,
    search: str = "",
    category: str = "",
    currency: str = "",
    tag_ids: list[int] | None = None,
) -> QuerySet[Asset]:
    qs = Asset.objects.filter(profile=profile).prefetch_related("tags")
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(instrument_symbol__icontains=search))
    if category:
        qs = qs.filter(category=category)
    if currency:
        qs = qs.filter(currency=currency)
    if tag_ids:
        qs = qs.filter(tags__id__in=tag_ids).distinct()
    return qs.order_by("-updated_at")


def create_asset(profile: Profile, *, tags: list[Tag] | None = None, **fields) -> Asset:
    asset = Asset.objects.create(profile=profile, **fields)
    if tags:
        asset.tags.set(tags)
    return asset


def update_asset(asset: Asset, *, tags: list[Tag] | None = None, **fields) -> Asset:
    for key, value in fields.items():
        setattr(asset, key, value)
    asset.save()
    if tags is not None:
        asset.tags.set(tags)
    return asset


def delete_asset(asset: Asset) -> None:
    asset.delete()


def distinct_currencies(profile: Profile) -> list[str]:
    return list(
        Asset.objects.filter(profile=profile)
        .values_list("currency", flat=True)
        .distinct()
        .order_by("currency")
    )

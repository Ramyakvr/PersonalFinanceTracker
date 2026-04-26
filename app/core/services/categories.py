"""Category management: list for the profile, toggle exempt, add custom, delete custom."""

from __future__ import annotations

from django.db.models import Q

from core.models import Category, Profile, TxType


def list_categories(profile: Profile, tx_type: str) -> list[Category]:
    qs = Category.objects.filter(
        Q(profile=profile) | Q(profile__isnull=True), type=tx_type
    ).order_by("name")
    return list(qs)


def list_all_categories(profile: Profile) -> dict[str, list[Category]]:
    return {
        "expense": list_categories(profile, TxType.EXPENSE),
        "income": list_categories(profile, TxType.INCOME),
    }


def set_exempt(category: Category, *, is_exempt: bool) -> Category:
    category.is_exempt = is_exempt
    category.save(update_fields=["is_exempt"])
    return category


def create_custom(
    profile: Profile, *, tx_type: str, name: str, is_exempt: bool = False
) -> Category:
    name = name.strip()
    if not name:
        raise ValueError("Category name cannot be empty.")
    category, created = Category.objects.get_or_create(
        profile=profile,
        type=tx_type,
        name=name,
        defaults={"is_custom": True, "is_exempt": is_exempt},
    )
    if not created and not category.is_custom:
        # Name collides with a system default — nothing to do, keep the default.
        return category
    return category


def delete_custom(category: Category) -> None:
    if not category.is_custom:
        raise ValueError("Only custom categories can be deleted.")
    category.delete()

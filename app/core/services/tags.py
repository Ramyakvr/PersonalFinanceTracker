"""Tag CRUD helpers shared across Asset, Liability, Transaction."""

from __future__ import annotations

from core.models import Profile, Tag


def parse_tags(profile: Profile, raw: str) -> list[Tag]:
    """Turn a comma-separated string into Tag rows, `get_or_create` per label.

    Labels are stripped and deduplicated case-insensitively (keeping the first spelling).
    """
    labels: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(","):
        clean = part.strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(clean)

    tags: list[Tag] = []
    for label in labels:
        tag, _ = Tag.objects.get_or_create(profile=profile, label=label)
        tags.append(tag)
    return tags


def serialize_tags(tags) -> str:
    """Turn a queryset/iterable of Tag rows into a comma-separated string for form editing."""
    return ", ".join(t.label for t in tags)

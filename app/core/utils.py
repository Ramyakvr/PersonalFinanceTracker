"""Small cross-cutting helpers that don't belong in a single model or service."""

from __future__ import annotations

from django.http import HttpRequest

from core.models import Profile


def get_active_profile(request: HttpRequest) -> Profile | None:
    """Return the default profile for the logged-in user, or None."""
    user = request.user
    if not user.is_authenticated:
        return None
    return user.profiles.filter(is_default=True).first()

"""Middleware for single-user auto-login and optional app-lock PIN gating.

Local-first behavior: we're the only user of our own machine. There's no signup/login form;
the `self` user (created by the seed command) is logged in automatically on every request.
On top of that, an optional 4-digit PIN gates access after inactivity — see core/auth.py.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse

from core.auth import is_session_unlocked
from core.models import User

PASSTHROUGH_PATHS = ("/auth/", "/static/", "/admin/")


class AutoLoginSelfMiddleware:
    """Log in the seeded `self` user on every request. No-op if already authenticated."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            user = User.objects.filter(username="self").first()
            if user:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)


class AppLockMiddleware:
    """If the logged-in user has set a PIN, require periodic re-entry via /auth/unlock."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if any(request.path.startswith(p) for p in PASSTHROUGH_PATHS):
            return self.get_response(request)

        user = request.user
        if not user.is_authenticated or not user.app_lock_hash:
            return self.get_response(request)

        timeout = getattr(settings, "APP_LOCK_TIMEOUT_SECONDS", 300)
        if is_session_unlocked(request.session, inactivity_seconds=timeout):
            return self.get_response(request)

        unlock_url = reverse("pin_unlock")
        return redirect(f"{unlock_url}?next={request.path}")

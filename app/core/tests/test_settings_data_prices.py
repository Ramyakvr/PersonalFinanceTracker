"""Settings → Data: live-price toggle tests."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from core.models import Profile, User, UserPreferences


@pytest.fixture
def client_and_user(db):
    user = User.objects.create(username="self", base_currency="INR")
    Profile.objects.create(user=user, name="Self", is_default=True)
    client = Client()
    client.force_login(user)
    return client, user


@pytest.mark.django_db
def test_settings_data_renders_toggle(client_and_user):
    client, _ = client_and_user
    resp = client.get(reverse("settings_data"))
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")
    assert "Live price fetch" in body
    assert 'name="live_price_enabled"' in body


@pytest.mark.django_db
def test_toggle_on_persists_preference(client_and_user):
    client, user = client_and_user
    resp = client.post(
        reverse("settings_data"),
        {"action": "toggle_live_prices", "live_price_enabled": "on"},
        follow=True,
    )
    assert resp.status_code == 200
    prefs = UserPreferences.objects.get(user=user)
    assert prefs.live_price_enabled is True


@pytest.mark.django_db
def test_toggle_off_persists_preference(client_and_user):
    client, user = client_and_user
    UserPreferences.objects.create(user=user, live_price_enabled=True)
    resp = client.post(
        reverse("settings_data"),
        {"action": "toggle_live_prices"},  # no checkbox value -> off
        follow=True,
    )
    assert resp.status_code == 200
    prefs = UserPreferences.objects.get(user=user)
    assert prefs.live_price_enabled is False

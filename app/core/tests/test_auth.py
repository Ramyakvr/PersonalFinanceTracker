from datetime import UTC, datetime, timedelta

import pytest
from django.test import Client

from core.auth import (
    LOCKOUT_SECONDS,
    MAX_ATTEMPTS,
    InvalidPinFormatError,
    is_session_unlocked,
    mark_unlocked,
    register_failed_attempt,
    session_locked_out,
    set_pin,
    verify_pin,
)
from core.models import User


@pytest.fixture
def user(db):
    return User.objects.create(username="self", base_currency="INR")


@pytest.mark.django_db
def test_set_and_verify_pin(user):
    set_pin(user, "4242")
    user.refresh_from_db()
    assert user.app_lock_hash
    assert user.app_lock_hash != "4242"
    assert verify_pin(user, "4242") is True
    assert verify_pin(user, "0000") is False


@pytest.mark.django_db
def test_invalid_pin_format_rejected(user):
    for bad in ["", "123", "12345", "abcd", "12 4"]:
        with pytest.raises(InvalidPinFormatError):
            set_pin(user, bad)


@pytest.mark.django_db
def test_verify_without_pin_returns_false(user):
    assert user.app_lock_hash == ""
    assert verify_pin(user, "4242") is False


def test_session_lockout_after_max_attempts():
    session: dict = {}
    for _ in range(MAX_ATTEMPTS):
        register_failed_attempt(session)
    locked, remaining = session_locked_out(session)
    assert locked is True
    assert 0 < remaining <= LOCKOUT_SECONDS


def test_session_not_locked_initially():
    assert session_locked_out({}) == (False, 0)


def test_mark_unlocked_resets_counters():
    session: dict = {"pin_attempts": 3, "pin_locked_until": "2099-01-01T00:00:00+00:00"}
    mark_unlocked(session)
    assert session["pin_attempts"] == 0
    assert "pin_locked_until" not in session
    assert "pin_unlocked_at" in session


def test_is_session_unlocked_respects_timeout():
    session: dict = {"pin_unlocked_at": datetime.now(UTC).isoformat()}
    assert is_session_unlocked(session, inactivity_seconds=60) is True

    session["pin_unlocked_at"] = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    assert is_session_unlocked(session, inactivity_seconds=60) is False

    assert is_session_unlocked({}, inactivity_seconds=60) is False


# --- view / middleware integration ----------------------------------------


@pytest.mark.django_db
def test_pin_set_view_sets_and_persists(user):
    response = Client().post("/auth/pin", {"pin": "4242", "confirm": "4242"})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.app_lock_hash
    assert verify_pin(user, "4242")


@pytest.mark.django_db
def test_pin_set_view_rejects_mismatch(user):
    response = Client().post("/auth/pin", {"pin": "4242", "confirm": "9999"})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.app_lock_hash == ""


@pytest.mark.django_db
def test_applock_middleware_redirects_when_locked(user):
    set_pin(user, "4242")
    client = Client()
    response = client.get("/")
    assert response.status_code == 302
    assert response["Location"].startswith("/auth/unlock")


@pytest.mark.django_db
def test_applock_unlocks_with_correct_pin(user):
    set_pin(user, "4242")
    client = Client()
    unlock = client.post("/auth/unlock", {"pin": "4242", "next": "/"})
    assert unlock.status_code == 302
    assert unlock["Location"] == "/"
    # Now hello page should render through
    hello = client.get("/")
    assert hello.status_code == 200
    assert b"Finance is running" in hello.content


@pytest.mark.django_db
def test_applock_wrong_pin_stays_on_unlock_page(user):
    set_pin(user, "4242")
    client = Client()
    response = client.post("/auth/unlock", {"pin": "0000", "next": "/"})
    assert response.status_code == 200
    assert b"Enter your PIN" in response.content


@pytest.mark.django_db
def test_pin_clear_removes_hash(user):
    set_pin(user, "4242")
    response = Client().post("/auth/pin", {"action": "clear"})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.app_lock_hash == ""

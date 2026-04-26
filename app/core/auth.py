"""App-lock PIN handling.

Rules:
- PIN is exactly 4 digits (0-9).
- Stored as an Argon2id hash in `User.app_lock_hash`. Never stored plaintext.
- Unlock writes `session["pin_unlocked_at"]` (ISO timestamp).
- Wrong attempts are counted in `session["pin_attempts"]`. After N failures the session
  is locked out for `LOCKOUT_SECONDS` before further attempts are accepted.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from core.models import User

PIN_REGEX = re.compile(r"^\d{4}$")
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60

_hasher = PasswordHasher()


class InvalidPinFormatError(ValueError):
    """Raised when a PIN is not exactly four digits."""


def _ensure_format(pin: str) -> None:
    if not isinstance(pin, str) or not PIN_REGEX.match(pin):
        raise InvalidPinFormatError("PIN must be exactly four digits (0-9).")


def set_pin(user: User, pin: str) -> None:
    """Hash and persist the PIN on the user row."""
    _ensure_format(pin)
    user.app_lock_hash = _hasher.hash(pin)
    user.save(update_fields=["app_lock_hash"])


def clear_pin(user: User) -> None:
    user.app_lock_hash = ""
    user.save(update_fields=["app_lock_hash"])


def verify_pin(user: User, pin: str) -> bool:
    """Return True on match. Does NOT raise on bad input; normalizes to False."""
    if not user.app_lock_hash:
        return False
    if not isinstance(pin, str) or not PIN_REGEX.match(pin):
        return False
    try:
        return _hasher.verify(user.app_lock_hash, pin)
    except (VerifyMismatchError, VerificationError):
        return False


def session_locked_out(session) -> tuple[bool, int]:
    """Return (is_locked_out, seconds_remaining) based on session counters."""
    locked_until = session.get("pin_locked_until")
    if not locked_until:
        return False, 0
    try:
        until = datetime.fromisoformat(locked_until)
    except ValueError:
        return False, 0
    now = datetime.now(UTC)
    if now >= until:
        return False, 0
    return True, int((until - now).total_seconds())


def register_failed_attempt(session) -> None:
    attempts = session.get("pin_attempts", 0) + 1
    session["pin_attempts"] = attempts
    if attempts >= MAX_ATTEMPTS:
        session["pin_locked_until"] = (
            datetime.now(UTC) + timedelta(seconds=LOCKOUT_SECONDS)
        ).isoformat()
        session["pin_attempts"] = 0


def mark_unlocked(session) -> None:
    session["pin_unlocked_at"] = datetime.now(UTC).isoformat()
    session["pin_attempts"] = 0
    session.pop("pin_locked_until", None)


def is_session_unlocked(session, *, inactivity_seconds: int) -> bool:
    raw = session.get("pin_unlocked_at")
    if not raw:
        return False
    try:
        unlocked = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return datetime.now(UTC) - unlocked < timedelta(seconds=inactivity_seconds)

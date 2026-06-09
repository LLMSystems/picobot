"""Password hashing helpers backed by argon2.

Centralised so the rest of the app never touches a raw hashing primitive and
we can re-tune argon2 parameters (or migrate algorithms) in one place.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

# Default argon2id parameters are a sane modern baseline; no need to tune for
# picobot's scale. One shared hasher instance is thread-safe.
_hasher = PasswordHasher()

# Keep registration cheap to reason about but reject the obviously-weak.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024  # guard against argon2 DoS via giant inputs


class WeakPasswordError(ValueError):
    """Raised when a password fails the minimum strength policy."""


def validate_password(password: str) -> None:
    """Raise WeakPasswordError if the password violates the policy."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError("Password is too long")


def hash_password(password: str) -> str:
    """Validate then hash a plaintext password. Returns the argon2 hash string."""
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True iff the plaintext matches the stored hash.

    Never raises on a normal mismatch — callers branch on the bool so login and
    register can return an identical generic error (no account enumeration).
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

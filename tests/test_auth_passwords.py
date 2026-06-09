"""Unit tests for the argon2 password helpers."""

import pytest

from simplified_chatbot.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    hash_password,
    validate_password,
    verify_password,
)


def test_hash_then_verify_roundtrip():
    password = "correct horse battery staple"
    h = hash_password(password)
    assert h != password
    assert h.startswith("$argon2")
    assert verify_password(h, password) is True


def test_verify_rejects_wrong_password():
    h = hash_password("right-password-1")
    assert verify_password(h, "wrong-password-1") is False


def test_verify_returns_false_on_garbage_hash():
    # Never raise on a malformed stored hash — callers must be able to bool-branch.
    assert verify_password("not-a-real-hash", "anything-goes") is False


def test_weak_password_rejected():
    with pytest.raises(WeakPasswordError):
        hash_password("short")


def test_validate_password_boundary():
    # Exactly MIN_PASSWORD_LENGTH must pass.
    validate_password("a" * MIN_PASSWORD_LENGTH)
    with pytest.raises(WeakPasswordError):
        validate_password("a" * (MIN_PASSWORD_LENGTH - 1))


def test_each_hash_is_unique_salt():
    # argon2 PHC strings embed a fresh salt → same password ≠ same hash.
    p = "same-password-twice"
    assert hash_password(p) != hash_password(p)

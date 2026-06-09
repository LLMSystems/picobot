import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_path():
    base = Path.cwd() / ".tmp_pytest"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="case_", dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def restore_environment():
    original = os.environ.copy()
    # Stable secret so /auth/* cookies survive across requests in a single test.
    os.environ.setdefault("SESSION_SECRET", "test-secret-not-for-production")
    # The default test user (register_test_user → "tester") is an admin so
    # dashboard tests reach the admin-only metrics/alerts routers. Tests that
    # exercise the non-admin path override ADMIN_USERNAMES in the test body.
    os.environ.setdefault("ADMIN_USERNAMES", "tester")
    try:
        yield
    finally:
        current_keys = list(os.environ.keys())
        for key in current_keys:
            if key not in original:
                os.environ.pop(key, None)
        os.environ.update(original)


def register_test_user(
    client,
    username: str = "tester",
    password: str = "test-password-123",
) -> dict:
    """Register and log in a user against a TestClient; returns the user payload.

    Endpoint tests use this so protected routes (Phase 2+) don't have to repeat
    the register/login boilerplate.
    """
    resp = client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 409:
        # Same DB reused across multiple TestClient instances in one test —
        # fall back to login so the cookie still ends up set.
        login = client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        if login.status_code == 200:
            return login.json()
        raise RuntimeError(
            f"register_test_user fallback login failed: {login.status_code} {login.text}"
        )
    raise RuntimeError(
        f"register_test_user failed: {resp.status_code} {resp.text}"
    )

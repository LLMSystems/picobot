"""Integration tests for the /auth/* endpoints (Phase 1)."""

import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("argon2")
pytest.importorskip("itsdangerous")

from fastapi.testclient import TestClient

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app
from simplified_chatbot.tools.filesystem import build_default_tool_registry


class _WorkspaceChatbot:
    def __init__(self, workspace_root):
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
            max_iterations=8,
        )
        self.tools = build_default_tool_registry(workspace=workspace_root)


def _build_runtime(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    return LocalAgentRuntime(
        chatbot=_WorkspaceChatbot(tmp_path / "base-workspace"),
        store=store,
        workspace_root_dir=tmp_path / "workspaces",
    )


def _client(tmp_path):
    # Pin SESSION_SECRET so cookies are stable across the TestClient instance.
    os.environ["SESSION_SECRET"] = "test-secret-not-for-production"
    runtime = _build_runtime(tmp_path)
    app = create_app(runtime=runtime)
    return TestClient(app)


def test_register_success_sets_cookie_and_returns_user(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/auth/register",
        json={"username": "alice", "password": "correct-horse"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == "alice"
    assert isinstance(body["id"], int) and body["id"] > 0
    assert any(c.name == "picobot_session" for c in client.cookies.jar)


def test_register_normalizes_username_case(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/auth/register",
        json={"username": "Bob", "password": "another-good-pwd"},
    )
    # Same name in a different case must collide.
    dup = client.post(
        "/auth/register",
        json={"username": "BOB", "password": "another-good-pwd"},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "USERNAME_TAKEN"


def test_register_rejects_weak_password(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/auth/register",
        json={"username": "carol", "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "WEAK_PASSWORD"


def test_login_success_after_register(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/auth/register",
        json={"username": "dave", "password": "good-password-1"},
    )
    client.cookies.clear()
    resp = client.post(
        "/auth/login",
        json={"username": "dave", "password": "good-password-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "dave"


def test_login_wrong_password_returns_401(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/auth/register",
        json={"username": "erin", "password": "good-password-2"},
    )
    client.cookies.clear()
    resp = client.post(
        "/auth/login",
        json={"username": "erin", "password": "WRONG-PASSWORD"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_user_returns_same_error_as_bad_password(tmp_path):
    # No account enumeration: missing user must match wrong-password.
    client = _client(tmp_path)
    resp = client.post(
        "/auth/login",
        json={"username": "ghost", "password": "whatever-pwd"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_me_requires_authentication(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_returns_current_user_after_login(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/auth/register",
        json={"username": "frank", "password": "good-password-3"},
    )
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "frank"


def test_logout_clears_session(tmp_path):
    client = _client(tmp_path)
    client.post(
        "/auth/register",
        json={"username": "gwen", "password": "good-password-4"},
    )
    assert client.get("/auth/me").status_code == 200
    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"ok": True}
    after = client.get("/auth/me")
    assert after.status_code == 401


def test_logout_is_idempotent_when_not_logged_in(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

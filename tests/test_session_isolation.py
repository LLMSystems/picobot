"""Phase 3 tests: sessions are owned by their creator and isolated per user."""

import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("argon2")

from fastapi.testclient import TestClient

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app
from simplified_chatbot.tools.filesystem import build_default_tool_registry


class _EchoResult:
    def __init__(self, *, messages, content):
        self.messages = messages
        self.content = content
        self.model = "dummy"
        self.provider = "dummy"
        self.usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        self.tools_used = []
        self.stop_reason = "stop"


class _WorkspaceChatbot:
    def __init__(self, workspace_root):
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
            max_iterations=8,
        )
        self.tools = build_default_tool_registry(workspace=workspace_root)

    async def run_async(self, message, history=None, *, on_event=None):
        history = history or []
        content = f"echo:{message}"
        messages = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": content},
        ]
        return _EchoResult(messages=messages, content=content)


def _build_app(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(
        chatbot=_WorkspaceChatbot(tmp_path / "base-workspace"),
        store=store,
        workspace_root_dir=tmp_path / "workspaces",
    )
    return create_app(runtime=runtime), runtime


def _client_for(app, username: str) -> TestClient:
    """A fresh TestClient (own cookie jar) logged in as a new user."""
    client = TestClient(app)
    resp = client.post(
        "/auth/register",
        json={"username": username, "password": "password-123"},
    )
    assert resp.status_code == 200, resp.text
    return client


def test_user_only_sees_own_sessions(tmp_path):
    app, _ = _build_app(tmp_path)
    alice = _client_for(app, "alice")
    bob = _client_for(app, "bob")

    created = alice.post("/sessions", json={"title": "alice secret"})
    assert created.status_code == 200
    sid = created.json()["session_id"]

    # Alice sees her session...
    alice_list = alice.get("/sessions").json()["sessions"]
    assert [s["session_id"] for s in alice_list] == [sid]

    # ...Bob does not.
    bob_list = bob.get("/sessions").json()["sessions"]
    assert bob_list == []


def test_other_user_cannot_read_session_messages(tmp_path):
    app, _ = _build_app(tmp_path)
    alice = _client_for(app, "alice")
    bob = _client_for(app, "bob")

    sid = alice.post("/sessions", json={"title": "x"}).json()["session_id"]

    # Owner can read; non-owner gets an indistinguishable 404.
    assert alice.get(f"/sessions/{sid}/messages").status_code == 200
    denied = bob.get(f"/sessions/{sid}/messages")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_other_user_cannot_access_workspace(tmp_path):
    app, _ = _build_app(tmp_path)
    alice = _client_for(app, "alice")
    bob = _client_for(app, "bob")

    sid = alice.post("/sessions", json={"title": "x"}).json()["session_id"]

    assert alice.get(f"/sessions/{sid}/workspace/tree").status_code == 200
    assert bob.get(f"/sessions/{sid}/workspace/tree").status_code == 404


def test_other_user_cannot_mutate_session(tmp_path):
    app, _ = _build_app(tmp_path)
    alice = _client_for(app, "alice")
    bob = _client_for(app, "bob")

    sid = alice.post("/sessions", json={"title": "x"}).json()["session_id"]

    # Rename and delete by a non-owner must 404, and the session must survive.
    assert bob.patch(f"/sessions/{sid}", json={"title": "hijacked"}).status_code == 404
    assert bob.delete(f"/sessions/{sid}").status_code == 404
    assert alice.get(f"/sessions/{sid}/messages").status_code == 200


def test_legacy_unowned_session_is_invisible(tmp_path):
    app, runtime = _build_app(tmp_path)
    # Simulate a pre-auth session row with no owner.
    asyncio.run(runtime.create_session_async(session_id="legacy", title="old"))

    alice = _client_for(app, "alice")
    assert alice.get("/sessions").json()["sessions"] == []
    assert alice.get("/sessions/legacy/messages").status_code == 404


def test_same_user_sees_sessions_across_logins(tmp_path):
    app, _ = _build_app(tmp_path)
    alice = _client_for(app, "alice")
    sid = alice.post("/sessions", json={"title": "x"}).json()["session_id"]

    # New client (fresh cookie jar) logs in as the same user.
    alice2 = TestClient(app)
    login = alice2.post("/auth/login", json={"username": "alice", "password": "password-123"})
    assert login.status_code == 200
    assert [s["session_id"] for s in alice2.get("/sessions").json()["sessions"]] == [sid]


def test_chat_into_new_session_assigns_owner(tmp_path):
    app, _ = _build_app(tmp_path)
    alice = _client_for(app, "alice")
    bob = _client_for(app, "bob")

    # Chatting into a brand-new session id implicitly creates it, owned by Alice.
    resp = alice.post("/chat", json={"session_id": "fresh", "message": "hi"})
    assert resp.status_code == 200

    assert [s["session_id"] for s in alice.get("/sessions").json()["sessions"]] == ["fresh"]
    # Bob cannot hijack it via chat.
    assert bob.post("/chat", json={"session_id": "fresh", "message": "mine now"}).status_code == 404

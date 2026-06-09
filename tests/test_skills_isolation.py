"""Custom skills are per-user: one user cannot see/delete another's skills."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("argon2")

from fastapi.testclient import TestClient

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app
from simplified_chatbot.skills.loader import SkillsLoader


class _SkillsChatbot:
    def __init__(self) -> None:
        self.config = ChatbotConfig(provider="openai_compat", model="gpt-5-mini")


def _skill_md(name: str, description: str) -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n"


def _app(tmp_path):
    loader = SkillsLoader(skills_dir=tmp_path / "skills")
    runtime = LocalAgentRuntime(
        chatbot=_SkillsChatbot(),
        store=AioSQLiteSessionStore(tmp_path / "sessions.db"),
        skills_loader=loader,
    )
    return create_app(runtime=runtime)


def _user_client(app, username: str) -> TestClient:
    client = TestClient(app)
    assert client.post(
        "/auth/register", json={"username": username, "password": "password-123"}
    ).status_code == 200
    return client


def _custom_names(client) -> set[str]:
    return {
        s["name"]
        for s in client.get("/skills").json()["skills"]
        if s["source"] == "custom"
    }


def test_custom_skills_are_not_visible_to_other_users(tmp_path):
    app = _app(tmp_path)
    alice = _user_client(app, "alice")
    bob = _user_client(app, "bob")

    assert alice.post(
        "/skills",
        json={"name": "alice-skill", "content": _skill_md("alice-skill", "alice only")},
    ).status_code == 200

    assert "alice-skill" in _custom_names(alice)
    assert "alice-skill" not in _custom_names(bob)


def test_other_user_cannot_delete_your_skill(tmp_path):
    app = _app(tmp_path)
    alice = _user_client(app, "alice")
    bob = _user_client(app, "bob")

    alice.post(
        "/skills",
        json={"name": "alice-skill", "content": _skill_md("alice-skill", "alice only")},
    )

    # For Bob the skill does not exist in his library → 404, and Alice keeps it.
    assert bob.delete("/skills/alice-skill").status_code == 404
    assert "alice-skill" in _custom_names(alice)


def test_shared_dir_disabled_state_applies_to_users(tmp_path):
    # A legacy/shared skill disabled via the global dir's .skill_state.json
    # must stay disabled for every user.
    import json

    skills_root = tmp_path / "skills"
    shared_skill = skills_root / "legacy"
    shared_skill.mkdir(parents=True)
    (shared_skill / "SKILL.md").write_text(_skill_md("legacy", "old shared"), encoding="utf-8")
    (skills_root / ".skill_state.json").write_text(
        json.dumps({"disabled": ["legacy"]}), encoding="utf-8"
    )

    loader = SkillsLoader(skills_dir=skills_root)
    runtime = LocalAgentRuntime(
        chatbot=_SkillsChatbot(),
        store=AioSQLiteSessionStore(tmp_path / "sessions.db"),
        skills_loader=loader,
    )
    app = create_app(runtime=runtime)
    alice = _user_client(app, "alice")

    entry = next(s for s in alice.get("/skills").json()["skills"] if s["name"] == "legacy")
    assert entry["source"] == "shared"
    assert entry["disabled"] is True


def test_same_name_skills_are_independent_per_user(tmp_path):
    app = _app(tmp_path)
    alice = _user_client(app, "alice")
    bob = _user_client(app, "bob")

    alice.post("/skills", json={"name": "notes", "content": _skill_md("notes", "alice notes")})
    bob.post("/skills", json={"name": "notes", "content": _skill_md("notes", "bob notes")})

    a = next(s for s in alice.get("/skills").json()["skills"] if s["name"] == "notes")
    b = next(s for s in bob.get("/skills").json()["skills"] if s["name"] == "notes")
    assert a["description"] == "alice notes"
    assert b["description"] == "bob notes"

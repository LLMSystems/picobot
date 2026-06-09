import base64
import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from conftest import register_test_user

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.server.app import create_app
from simplified_chatbot.skills.loader import SkillsLoader


class _SkillsChatbot:
    def __init__(self) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
        )


def _build_client(tmp_path):
    skills_dir = tmp_path / "custom_skills"
    loader = SkillsLoader(skills_dir=skills_dir)
    runtime = LocalAgentRuntime(
        chatbot=_SkillsChatbot(),
        skills_loader=loader,
    )
    client = TestClient(create_app(runtime=runtime))
    user = register_test_user(client)
    # Custom skills are now stored per-user under <skills_dir>/users/<id>.
    user_dir = skills_dir / "users" / str(user["id"])
    return client, user_dir


def _skill_markdown(name: str, description: str = "Demo skill") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n"
        "\n"
        "# Demo\n"
        "Use this skill for testing.\n"
    )


def test_skills_endpoints_create_list_disable_and_delete(tmp_path):
    client, skills_dir = _build_client(tmp_path)
    attachment = base64.b64encode(b"reference notes").decode("ascii")

    create_response = client.post(
        "/skills",
        json={
            "name": "demo-skill",
            "content": _skill_markdown("demo-skill", "Created in a test"),
            "files": [
                {
                    "path": "references/notes.txt",
                    "content_base64": attachment,
                },
            ],
        },
    )

    assert create_response.status_code == 200
    assert create_response.json() == {"name": "demo-skill", "ok": True}
    assert (skills_dir / "demo-skill" / "SKILL.md").exists()
    assert (
        skills_dir / "demo-skill" / "references" / "notes.txt"
    ).read_bytes() == b"reference notes"

    list_response = client.get("/skills")
    assert list_response.status_code == 200
    custom = next(
        item for item in list_response.json()["skills"]
        if item["name"] == "demo-skill"
    )
    assert custom == {
        "name": "demo-skill",
        "source": "custom",
        "description": "Created in a test",
        "always": False,
        "disabled": False,
    }

    disable_response = client.patch(
        "/skills/demo-skill",
        json={"disabled": True},
    )
    assert disable_response.status_code == 200
    assert disable_response.json() == {"name": "demo-skill", "ok": True}

    state = json.loads((skills_dir / ".skill_state.json").read_text(encoding="utf-8"))
    assert state == {"disabled": ["demo-skill"]}
    disabled_list = client.get("/skills").json()["skills"]
    disabled_entry = next(
        item for item in disabled_list
        if item["name"] == "demo-skill"
    )
    assert disabled_entry["disabled"] is True

    delete_response = client.delete("/skills/demo-skill")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"name": "demo-skill", "ok": True}
    assert not (skills_dir / "demo-skill").exists()
    assert all(
        item["name"] != "demo-skill"
        for item in client.get("/skills").json()["skills"]
    )


def test_create_skill_rejects_invalid_base64(tmp_path):
    client, _skills_dir = _build_client(tmp_path)

    response = client.post(
        "/skills",
        json={
            "name": "broken-skill",
            "content": _skill_markdown("broken-skill"),
            "files": [
                {
                    "path": "references/notes.txt",
                    "content_base64": "%%%not-base64%%%",
                },
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SKILL_FILE_INVALID"


def test_delete_builtin_skill_is_rejected(tmp_path):
    client, _skills_dir = _build_client(tmp_path)

    response = client.delete("/skills/agent-browser")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SKILL_BUILTIN_READ_ONLY"

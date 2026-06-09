import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient
from conftest import register_test_user

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
    runtime = LocalAgentRuntime(
        chatbot=_WorkspaceChatbot(tmp_path / "base-workspace"),
        store=store,
        workspace_root_dir=tmp_path / "workspaces",
        max_upload_file_bytes=128,
        max_upload_files_per_request=2,
    )
    return runtime


def test_capabilities_exposes_file_upload(tmp_path):
    runtime = _build_runtime(tmp_path)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json()["features"]["file_upload"] is True


def test_upload_workspace_file_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/upload",
        files=[("files", ("notes.md", b"# Notes\nHello\n", "text/markdown"))],
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": ".",
        "uploaded": [
            {
                "path": "notes.md",
                "name": "notes.md",
                "size": 14,
                "content_type": "text/markdown",
                "overwritten": False,
            },
        ],
        "skipped": [],
    }

    file_response = client.get(
        "/sessions/s1/workspace/file",
        params={"path": "notes.md"},
    )
    assert file_response.status_code == 200
    assert file_response.json()["content"] == "# Notes\nHello\n"


def test_upload_workspace_file_skips_existing_without_overwrite(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "notes.md").write_text("old\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/upload",
        files=[("files", ("notes.md", b"new\n", "text/plain"))],
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": ".",
        "uploaded": [],
        "skipped": [
            {
                "name": "notes.md",
                "reason": "already_exists",
            },
        ],
    }
    assert (workspace / "notes.md").read_text(encoding="utf-8") == "old\n"


def test_upload_workspace_file_with_overwrite_replaces_existing(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    docs = workspace / "docs"
    docs.mkdir(parents=True)
    (docs / "notes.md").write_text("old\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/upload",
        params={"path": "docs", "overwrite": "true"},
        files=[("files", ("notes.md", b"new\n", "text/plain"))],
    )

    assert response.status_code == 200
    assert response.json()["uploaded"][0]["overwritten"] is True
    assert (docs / "notes.md").read_text(encoding="utf-8") == "new\n"


def test_upload_workspace_file_rejects_invalid_filename(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/upload",
        files=[("files", ("../secret.txt", b"x", "text/plain"))],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_UPLOAD_FILENAME_INVALID"


def test_upload_workspace_file_enforces_max_files(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/upload",
        files=[
            ("files", ("a.txt", b"a", "text/plain")),
            ("files", ("b.txt", b"b", "text/plain")),
            ("files", ("c.txt", b"c", "text/plain")),
        ],
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "WORKSPACE_UPLOAD_TOO_MANY_FILES"


def test_delete_workspace_file_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "notes.md").write_text("hello\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.delete(
        "/sessions/s1/workspace/file",
        params={"path": "notes.md"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": "notes.md",
        "deleted": True,
    }
    assert not (workspace / "notes.md").exists()


def test_create_workspace_directory_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/mkdir",
        json={"path": "drafts/2026-05"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": "drafts/2026-05",
        "created": True,
    }
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    assert (workspace / "drafts" / "2026-05").is_dir()


def test_create_workspace_directory_returns_false_when_existing(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "drafts" / "2026-05").mkdir(parents=True)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/mkdir",
        json={"path": "drafts/2026-05"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": "drafts/2026-05",
        "created": False,
    }


def test_create_workspace_directory_rejects_existing_file(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "drafts.txt").write_text("hello\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/mkdir",
        json={"path": "drafts.txt"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_A_DIRECTORY"


def test_upload_workspace_file_requires_existing_session(tmp_path):
    runtime = _build_runtime(tmp_path)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/missing/workspace/upload",
        files=[("files", ("notes.md", b"hello", "text/plain"))],
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_create_workspace_directory_requires_existing_session(tmp_path):
    runtime = _build_runtime(tmp_path)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/missing/workspace/mkdir",
        json={"path": "drafts"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_move_workspace_file_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir(parents=True)
    (workspace / "archive" / "2026").mkdir(parents=True)
    (workspace / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs/notes.md",
            "dst": "archive/2026/notes.md",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "src": "docs/notes.md",
        "dst": "archive/2026/notes.md",
        "type": "file",
        "overwritten": False,
    }
    assert not (workspace / "docs" / "notes.md").exists()
    assert (workspace / "archive" / "2026" / "notes.md").read_text(encoding="utf-8") == "hello\n"


def test_move_workspace_file_overwrite_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir(parents=True)
    (workspace / "archive").mkdir(parents=True)
    (workspace / "docs" / "notes.md").write_text("new\n", encoding="utf-8")
    (workspace / "archive" / "notes.md").write_text("old\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs/notes.md",
            "dst": "archive/notes.md",
            "overwrite": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["overwritten"] is True
    assert not (workspace / "docs" / "notes.md").exists()
    assert (workspace / "archive" / "notes.md").read_text(encoding="utf-8") == "new\n"


def test_move_workspace_file_requires_existing_source(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "archive").mkdir(parents=True)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "missing.txt",
            "dst": "archive/missing.txt",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKSPACE_FILE_NOT_FOUND"


def test_move_workspace_file_requires_existing_destination_parent(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs/notes.md",
            "dst": "archive/2026/notes.md",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKSPACE_DIRECTORY_NOT_FOUND"


def test_move_workspace_file_rejects_existing_destination_without_overwrite(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir(parents=True)
    (workspace / "archive").mkdir(parents=True)
    (workspace / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
    (workspace / "archive" / "notes.md").write_text("old\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs/notes.md",
            "dst": "archive/notes.md",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_MOVE_DESTINATION_EXISTS"


def test_move_workspace_file_rejects_directory_destination_even_with_overwrite(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir(parents=True)
    (workspace / "archive").mkdir(parents=True)
    (workspace / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
    (workspace / "archive" / "notes.md").mkdir(parents=True)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs/notes.md",
            "dst": "archive/notes.md",
            "overwrite": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_MOVE_DESTINATION_IS_DIRECTORY"


def test_move_workspace_file_rejects_same_path(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "notes.md").write_text("hello\n", encoding="utf-8")
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs/notes.md",
            "dst": "docs/notes.md",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_MOVE_SAME_PATH"


def test_move_workspace_file_rejects_workspace_root_source(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "archive").mkdir(parents=True)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": ".",
            "dst": "archive/root",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_MOVE_ROOT_FORBIDDEN"


def test_move_workspace_directory_rejects_moving_into_self(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs" / "sub").mkdir(parents=True)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "docs",
            "dst": "docs/sub/docs",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_MOVE_INTO_SELF"


def test_move_workspace_file_rejects_path_traversal(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/move",
        json={
            "src": "../secret.txt",
            "dst": "docs/secret.txt",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_PATH_INVALID"


def test_move_workspace_file_requires_existing_session(tmp_path):
    runtime = _build_runtime(tmp_path)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post(
        "/sessions/missing/workspace/move",
        json={
            "src": "notes.md",
            "dst": "archive/notes.md",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"

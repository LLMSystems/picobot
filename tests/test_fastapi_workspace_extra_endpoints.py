import asyncio
import io
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient
from conftest import register_test_user

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app
from simplified_chatbot.server import endpoints_workspace
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
    )
    return runtime


def test_get_workspace_file_raw_returns_bytes_and_headers(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    content = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    (workspace / "diagram.svg").write_bytes(content)
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.get(
        "/sessions/s1/workspace/file/raw",
        params={"path": "diagram.svg"},
    )

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_get_workspace_file_raw_rejects_large_files(tmp_path, monkeypatch):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "big.bin").write_bytes(b"1234")
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    monkeypatch.setattr(endpoints_workspace, "_RAW_MAX_BYTES", 3)

    response = client.get(
        "/sessions/s1/workspace/file/raw",
        params={"path": "big.bin"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "WORKSPACE_FILE_TOO_LARGE"


def test_download_workspace_zip_returns_archive_contents(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (workspace / "docs" / "todo.txt").write_text("item\n", encoding="utf-8")
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.get(
        "/sessions/s1/workspace/download",
        params={"path": "docs"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "docs.zip" in response.headers["content-disposition"]

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert sorted(archive.namelist()) == ["notes.md", "todo.txt"]
    assert archive.read("notes.md").replace(b"\r\n", b"\n") == b"# Notes\n"


def test_create_workspace_file_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir()
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/file",
        json={"path": "docs/new.md", "content": "hello\n"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": "docs/new.md",
        "created": True,
    }
    assert (workspace / "docs" / "new.md").read_text(encoding="utf-8") == "hello\n"


def test_create_workspace_file_rejects_existing_without_overwrite(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "new.md").write_text("old\n", encoding="utf-8")
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.post(
        "/sessions/s1/workspace/file",
        json={"path": "docs/new.md", "content": "hello\n"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_FILE_ALREADY_EXISTS"


def test_save_workspace_file_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "draft.md").write_text("old\n", encoding="utf-8")
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.put(
        "/sessions/s1/workspace/file",
        json={"path": "docs/draft.md", "content": "new\n"},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "s1"
    assert response.json()["path"] == "docs/draft.md"
    assert response.json()["saved"] is True
    assert response.json()["size"] == 4
    assert response.json()["updated_at"].endswith("+00:00")
    assert (workspace / "docs" / "draft.md").read_text(encoding="utf-8") == "new\n"


def test_save_workspace_file_requires_existing_parent_directory(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.put(
        "/sessions/s1/workspace/file",
        json={"path": "missing/draft.md", "content": "new\n"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WORKSPACE_DIRECTORY_NOT_FOUND"


def test_delete_workspace_directory_recursive_success(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs" / "nested").mkdir(parents=True)
    (workspace / "docs" / "nested" / "note.txt").write_text("hello\n", encoding="utf-8")
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.delete(
        "/sessions/s1/workspace/directory",
        params={"path": "docs", "recursive": "true"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": "docs",
        "deleted": True,
    }
    assert not (workspace / "docs").exists()


def test_delete_workspace_directory_rejects_non_empty_without_recursive(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "note.txt").write_text("hello\n", encoding="utf-8")
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.delete(
        "/sessions/s1/workspace/directory",
        params={"path": "docs"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORKSPACE_DIRECTORY_NOT_EMPTY"


def test_delete_workspace_directory_rejects_workspace_root(tmp_path):
    runtime = _build_runtime(tmp_path)
    asyncio.run(runtime.create_session_async(session_id="s1", title="demo", user_id=1))
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    response = client.delete(
        "/sessions/s1/workspace/directory",
        params={"path": "."},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_DELETE_ROOT_FORBIDDEN"

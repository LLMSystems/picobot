from pathlib import Path

from eval.scripts.collect_browser_data import (
    CollectionCase,
    _build_collection_summary,
    _extract_agent_browser_commands,
    _extract_exec_traces,
    collect_case,
    create_collection_dir,
    load_collection_dataset,
)
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager


class _DummyResult:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage = {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}
        self.tools_used = ["exec", "write_file"]
        self.stop_reason = "stop"
        self.messages = [
            {"role": "user", "content": "open page"},
            {"role": "assistant", "content": content},
        ]


class _FakeBrowserCollectionRuntime:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_manager = SessionWorkspaceManager(workspace_root)

    def create_session(self, *, session_id: str, title: str) -> None:
        self.workspace_manager.ensure_workspace(session_id)

    def handle_message_with_events(self, session_id: str, prompt: str, *, on_event=None):
        workspace = self.workspace_manager.ensure_workspace(session_id)
        artifacts = workspace / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "final_notes.txt").write_text("Page shows Sign in\n", encoding="utf-8")
        (artifacts / "final.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        if on_event is not None:
            on_event(
                "tool_call_started",
                {
                    "id": "call_1",
                    "name": "exec",
                    "arguments": {
                        "command": "agent-browser --headed false open http://127.0.0.1:3000",
                        "working_dir": ".",
                        "timeout": 60,
                    },
                },
            )
            on_event(
                "tool_call_finished",
                {
                    "id": "call_1",
                    "name": "exec",
                    "ok": True,
                    "result": "opened",
                },
            )
        return _DummyResult(content=f"handled:{prompt}")


def test_load_collection_dataset_parses_jsonl(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        '{"id":"browser_1","prompt":"open page"}\n'
        '{"id":"browser_2","prompt":"take screenshot","tags":["browser"]}\n',
        encoding="utf-8",
    )

    cases = load_collection_dataset(dataset_path)

    assert [case.id for case in cases] == ["browser_1", "browser_2"]
    assert cases[0].setup_files == []
    assert cases[1].tags == ["browser"]


def test_create_collection_dir_adds_suffix_when_name_exists(tmp_path: Path):
    first = create_collection_dir(tmp_path, run_name="demo")
    second = create_collection_dir(tmp_path, run_name="demo")

    assert first.name == "demo"
    assert second.name == "demo_02"


def test_extract_exec_traces_and_agent_browser_commands():
    events = [
        {
            "event": "tool_call_started",
            "data": {
                "id": "call_1",
                "name": "exec",
                "arguments": {
                    "command": "agent-browser --headed false open http://127.0.0.1:3000",
                    "working_dir": ".",
                    "timeout": 60,
                },
            },
        },
        {
            "event": "tool_call_finished",
            "data": {
                "id": "call_1",
                "name": "exec",
                "ok": True,
                "result": "opened",
            },
        },
    ]

    traces = _extract_exec_traces(events)

    assert traces == [
        {
            "id": "call_1",
            "command": "agent-browser --headed false open http://127.0.0.1:3000",
            "working_dir": ".",
            "timeout": 60,
            "ok": True,
            "result": "opened",
            "error": None,
        },
    ]
    assert _extract_agent_browser_commands(events) == [
        "agent-browser --headed false open http://127.0.0.1:3000",
    ]


def test_collect_case_captures_exec_and_workspace_artifacts(tmp_path: Path):
    runtime = _FakeBrowserCollectionRuntime(tmp_path / "workspaces")
    case = CollectionCase.from_payload(
        {
            "id": "browser_collect_001",
            "prompt": "open page and save artifacts",
            "tags": ["browser"],
        },
    )

    result = collect_case(runtime, case)

    assert result["status"] == "completed"
    assert result["agent_browser_commands"] == [
        "agent-browser --headed false open http://127.0.0.1:3000",
    ]
    assert result["browser_artifacts"]["screenshot_files"] == ["artifacts/final.png"]
    assert result["browser_artifacts"]["document_files"] == ["artifacts/final_notes.txt"]
    assert any(
        file_item["path"] == "artifacts/final_notes.txt"
        and "Page shows Sign in" in str(file_item.get("content_preview", ""))
        for file_item in result["workspace"]["files"]
    )


def test_build_collection_summary_counts_browser_cases(tmp_path: Path):
    summary = _build_collection_summary(
        run_dir=tmp_path / "run_01",
        config_path=tmp_path / "config.json",
        dataset_path=tmp_path / "dataset.jsonl",
        results=[
            {
                "id": "case_1",
                "status": "completed",
                "agent_browser_commands": ["agent-browser --headed false open http://127.0.0.1:3000"],
                "workspace": {"files": [{"path": "artifacts/final.txt"}]},
            },
            {
                "id": "case_2",
                "status": "failed",
                "agent_browser_commands": [],
                "workspace": {"files": []},
            },
        ],
    )

    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["cases_with_agent_browser_commands"] == 1

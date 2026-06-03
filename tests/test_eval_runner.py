from pathlib import Path

from eval.scripts.run_eval import (
    EvalCase,
    _build_run_summary,
    create_run_dir,
    load_dataset,
    run_case,
)
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager


class _DummyResult:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        self.tools_used = ["write_file"]
        self.stop_reason = "stop"


class _FakeRuntime:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_manager = SessionWorkspaceManager(workspace_root)
        self.created_sessions: list[tuple[str, str]] = []

    def create_session(self, *, session_id: str, title: str) -> None:
        self.created_sessions.append((session_id, title))
        self.workspace_manager.ensure_workspace(session_id)

    def handle_message_with_events(self, session_id: str, prompt: str, *, on_event=None):
        workspace = self.workspace_manager.ensure_workspace(session_id)
        output_path = workspace / "doc" / "summary.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# Summary\nGenerated\n", encoding="utf-8")
        if on_event is not None:
            on_event("tool_call_started", {"id": "call_1", "name": "write_file"})
            on_event(
                "tool_call_finished",
                {"id": "call_1", "name": "write_file", "ok": True, "result": "ok"},
            )
        return _DummyResult(content=f"handled:{prompt}")


def test_load_dataset_parses_jsonl_and_defaults(tmp_path: Path):
    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        '{"id":"case_1","prompt":"hello"}\n'
        '{"id":"case_2","category":"chat","prompt":"world","tags":["a"]}\n',
        encoding="utf-8",
    )

    cases = load_dataset(dataset_path)

    assert [case.id for case in cases] == ["case_1", "case_2"]
    assert cases[0].category == "uncategorized"
    assert cases[0].tags == []
    assert cases[1].tags == ["a"]


def test_create_run_dir_adds_suffix_when_name_exists(tmp_path: Path):
    first = create_run_dir(tmp_path, run_name="demo")
    second = create_run_dir(tmp_path, run_name="demo")

    assert first.name == "demo"
    assert second.name == "demo_02"


def test_run_case_prepares_workspace_and_collects_outputs(tmp_path: Path):
    runtime = _FakeRuntime(tmp_path / "workspaces")
    case = EvalCase.from_payload(
        {
            "id": "workspace_001",
            "category": "workspace_write",
            "prompt": "write summary",
            "setup_files": [
                {"path": "README.md", "content": "# Source\n"},
            ],
            "expected_files": [
                {"path": "doc/summary.md", "must_exist": True},
            ],
            "expected_contains": ["handled"],
            "expected_tools": ["write_file"],
            "tags": ["workspace"],
        },
    )

    result = run_case(runtime, case)

    workspace = runtime.workspace_manager.ensure_workspace("eval_workspace_001")
    assert (workspace / "README.md").read_text(encoding="utf-8") == "# Source\n"
    assert result["status"] == "completed"
    assert result["content"] == "handled:write summary"
    assert result["workspace_outputs"][0]["path"] == "doc/summary.md"
    assert result["workspace_outputs"][0]["exists"] is True
    assert result["workspace_outputs"][0]["is_file"] is True
    assert result["workspace_outputs"][0]["size"] > 0
    assert len(result["workspace_outputs"][0]["sha256"]) == 64
    assert result["workspace_outputs"][0]["content"] == "# Summary\r\nGenerated\r\n"
    assert result["score"]["pass"] is True
    assert result["score"]["failed_checks"] == 0


def test_run_case_scores_failed_expectations(tmp_path: Path):
    runtime = _FakeRuntime(tmp_path / "workspaces")
    case = EvalCase.from_payload(
        {
            "id": "workspace_002",
            "category": "workspace_write",
            "prompt": "write summary",
            "expected_contains": ["missing-text"],
            "forbidden_contains": ["handled"],
            "expected_tools": ["read_file"],
            "expected_files": [
                {
                    "path": "doc/summary.md",
                    "must_exist": True,
                    "content_contains": ["Not Here"],
                },
            ],
        },
    )

    result = run_case(runtime, case)

    assert result["score"]["pass"] is False
    assert result["score"]["failed_checks"] == 4
    assert any(
        check["name"] == "expected_file_content_contains" and not check["passed"]
        for check in result["score"]["checks"]
    )


def test_build_run_summary_includes_scoring_and_categories(tmp_path: Path):
    results = [
        {
            "id": "case_pass",
            "category": "chat",
            "status": "completed",
            "score": {"pass": True},
        },
        {
            "id": "case_fail",
            "category": "workspace",
            "status": "failed",
            "score": {"pass": False},
        },
    ]

    summary = _build_run_summary(
        run_dir=tmp_path / "run_01",
        config_path=tmp_path / "config.json",
        dataset_path=tmp_path / "dataset.jsonl",
        results=results,
    )

    assert summary["rule_pass"] == 1
    assert summary["rule_fail"] == 1
    assert summary["rule_pass_rate"] == 0.5
    assert summary["final_pass"] == 0
    assert summary["final_fail"] == 2
    assert summary["categories"]["chat"]["rule_pass"] == 1
    assert summary["categories"]["workspace"]["failed"] == 1
    assert summary["cases"] == [
        {
            "id": "case_pass",
            "status": "completed",
            "category": "chat",
            "rule_pass": True,
            "llm_judge_pass": None,
            "final_pass": False,
        },
        {
            "id": "case_fail",
            "status": "failed",
            "category": "workspace",
            "rule_pass": False,
            "llm_judge_pass": None,
            "final_pass": False,
        },
    ]

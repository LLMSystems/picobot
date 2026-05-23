import asyncio
import base64
import json
from pathlib import Path

from eval.scripts.llm_judge import (
    JudgeEvidence,
    build_judge_evidence,
    image_file_to_data_url,
    judge_run_async,
    parse_judge_output,
    render_judge_text_packet,
)


def _build_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run_01"
    (run_dir / "cases").mkdir(parents=True)
    (run_dir / "workspaces" / "eval_browser_v1_001" / "artifacts").mkdir(parents=True)
    return run_dir


def test_build_judge_evidence_selects_text_and_image_artifacts(tmp_path: Path):
    run_dir = _build_run_dir(tmp_path)
    notes = run_dir / "workspaces" / "eval_browser_v1_001" / "artifacts" / "final_notes.txt"
    image = run_dir / "workspaces" / "eval_browser_v1_001" / "artifacts" / "final.png"
    notes.write_text("Page shows Sign in\n", encoding="utf-8")
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    case_result = {
        "id": "browser_v1_001",
        "category": "browser_cli",
        "prompt": "Open page and save artifacts",
        "session_id": "eval_browser_v1_001",
        "content": "Done",
        "workspace_outputs": [
            {
                "path": "artifacts/final_notes.txt",
                "exists": True,
                "is_file": True,
                "content": "Page shows Sign in\n",
            },
            {
                "path": "artifacts/final.png",
                "exists": True,
                "is_file": True,
                "content": None,
            },
        ],
        "events": [],
    }

    evidence = build_judge_evidence(run_dir, case_result)

    assert evidence.case_id == "browser_v1_001"
    assert evidence.skill_context is not None
    assert "Always pass `--headed false`" in evidence.skill_context
    assert evidence.text_artifacts == [
        {
            "path": "artifacts/final_notes.txt",
            "content": "Page shows Sign in\n",
        },
    ]
    assert evidence.image_artifacts == [
        {
            "path": "artifacts/final.png",
            "absolute_path": str(image.resolve()),
        },
    ]


def test_render_judge_text_packet_contains_expected_sections():
    evidence = JudgeEvidence(
        case_id="browser_v1_001",
        category="browser_cli",
        task_prompt="Open the page",
        assistant_answer="Done",
        skill_context="Always pass `--headed false`.",
        text_artifacts=[{"path": "artifacts/final_notes.txt", "content": "Sign in"}],
        image_artifacts=[{"path": "artifacts/final.png", "absolute_path": "/tmp/final.png"}],
        trace_summary={"agent_browser_command_count": 2},
    )

    packet = render_judge_text_packet(evidence)

    assert "[Task]" in packet
    assert "Open the page" in packet
    assert "[Relevant Skill Rules]" in packet
    assert "Always pass `--headed false`." in packet
    assert "[Available Image Artifacts]" in packet
    assert "artifacts/final.png" in packet
    assert '"agent_browser_command_count": 2' in packet


def test_image_file_to_data_url_returns_base64_data_url(tmp_path: Path):
    image = tmp_path / "final.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    data_url = image_file_to_data_url(image)

    assert data_url.startswith("data:image/png;base64,")
    encoded = data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"\x89PNG\r\n\x1a\nfake"


def test_parse_judge_output_handles_plain_json_and_wrapped_json():
    assert parse_judge_output('{"pass": true, "score": 0.9, "reason": "ok", "evidence_used": []}')["pass"] is True

    wrapped = """
    Here is the verdict:
    {"pass": false, "score": 0.2, "reason": "not enough evidence", "evidence_used": []}
    """
    assert parse_judge_output(wrapped)["pass"] is False


def test_judge_run_async_saves_case_outputs(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    run_dir = _build_run_dir(project_root)
    notes = run_dir / "workspaces" / "eval_browser_v1_001" / "artifacts" / "final_notes.txt"
    image = run_dir / "workspaces" / "eval_browser_v1_001" / "artifacts" / "final.png"
    notes.write_text("Page shows Sign in\n", encoding="utf-8")
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    case_result = {
        "id": "browser_v1_001",
        "category": "browser_cli",
        "prompt": "Open page and save artifacts",
        "session_id": "eval_browser_v1_001",
        "status": "completed",
        "content": "Done",
        "workspace_outputs": [
            {
                "path": "artifacts/final_notes.txt",
                "exists": True,
                "is_file": True,
                "content": "Page shows Sign in\n",
            },
            {
                "path": "artifacts/final.png",
                "exists": True,
                "is_file": True,
                "content": None,
            },
        ],
        "events": [],
    }
    (run_dir / "cases" / "browser_v1_001.json").write_text(
        json.dumps(case_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    class _FakeResponses:
        async def create(self, **kwargs):
            class _Resp:
                output_text = '{"pass": true, "score": 0.95, "reason": "clear success", "evidence_used": ["artifacts/final_notes.txt", "artifacts/final.png"]}'

            return _Resp()

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.responses = _FakeResponses()

    monkeypatch.setattr("eval.scripts.llm_judge.AsyncOpenAI", _FakeClient)

    output_dir = asyncio.run(
        judge_run_async(
            config_path,
            run_dir,
            judge_model="gpt-4.1-mini",
            detail="high",
        ),
    )

    case_output = json.loads((output_dir / "cases" / "browser_v1_001.json").read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))

    assert case_output["verdict"]["pass"] is True
    assert case_output["evidence"]["skill_context"] is not None
    assert case_output["evidence"]["image_artifacts"][0]["path"] == "artifacts/final.png"
    assert summary["case_count"] == 1
    assert summary["passed"] == 1

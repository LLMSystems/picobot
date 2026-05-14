"""Minimal local eval runner for picobot."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime


@dataclass(slots=True)
class EvalCase:
    """One eval case loaded from a JSONL dataset."""

    id: str
    category: str
    prompt: str
    setup_files: list[dict[str, str]]
    expected_contains: list[str]
    forbidden_contains: list[str]
    expected_tools: list[str]
    expected_files: list[dict[str, Any]]
    tags: list[str]
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EvalCase":
        case_id = str(payload.get("id", "")).strip()
        if not case_id:
            raise ValueError("Eval case is missing a non-empty 'id'")
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            raise ValueError(f"Eval case '{case_id}' is missing a non-empty 'prompt'")
        category = str(payload.get("category", "uncategorized")).strip() or "uncategorized"
        return cls(
            id=case_id,
            category=category,
            prompt=prompt,
            setup_files=_coerce_list_of_dicts(payload.get("setup_files")),
            expected_contains=_coerce_list_of_strings(payload.get("expected_contains")),
            forbidden_contains=_coerce_list_of_strings(payload.get("forbidden_contains")),
            expected_tools=_coerce_list_of_strings(payload.get("expected_tools")),
            expected_files=_coerce_list_of_dicts(payload.get("expected_files")),
            tags=_coerce_list_of_strings(payload.get("tags")),
            raw=dict(payload),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a minimal local eval dataset against picobot.",
    )
    parser.add_argument("config", help="Path to chatbot config JSON.")
    parser.add_argument("dataset", help="Path to eval dataset JSONL.")
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "eval" / "runs"),
        help="Directory where eval run folders should be created.",
    )
    parser.add_argument(
        "--run-name",
        default=None,
        help="Optional fixed run name. If omitted, a timestamp-based name is used.",
    )
    return parser


def load_dataset(path: str | Path) -> list[EvalCase]:
    dataset_path = Path(path).expanduser().resolve()
    cases: list[EvalCase] = []
    for line_number, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"Dataset line {line_number} must be a JSON object")
        cases.append(EvalCase.from_payload(payload))
    if not cases:
        raise ValueError(f"Dataset '{dataset_path}' did not contain any eval cases")
    return cases


def create_run_dir(output_root: str | Path, run_name: str | None = None) -> Path:
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    base = run_name or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    candidate = root / base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    (candidate / "cases").mkdir(parents=True, exist_ok=True)
    return candidate


def run_case(
    runtime: LocalAgentRuntime,
    case: EvalCase,
) -> dict[str, Any]:
    session_id = f"eval_{case.id}"
    events: list[dict[str, Any]] = []

    def on_event(event: str, data: dict[str, Any]) -> None:
        events.append({"event": event, "data": data})

    _create_session_if_supported(runtime, session_id=session_id, title=case.id)
    _prepare_workspace(runtime, session_id=session_id, case=case)

    try:
        result = runtime.handle_message_with_events(
            session_id,
            case.prompt,
            on_event=on_event,
        )
    except Exception as exc:
        failed_result = {
            "id": case.id,
            "category": case.category,
            "prompt": case.prompt,
            "session_id": session_id,
            "status": "failed",
            "error": str(exc),
            "events": events,
            "tags": case.tags,
            "workspace_outputs": _collect_workspace_outputs(runtime, session_id, case),
        }
        failed_result["score"] = _score_case(case, failed_result)
        return failed_result

    completed_result = {
        "id": case.id,
        "category": case.category,
        "prompt": case.prompt,
        "session_id": session_id,
        "status": "completed",
        "content": result.content,
        "usage": result.usage,
        "tools_used": result.tools_used,
        "stop_reason": result.stop_reason,
        "events": events,
        "tags": case.tags,
        "workspace_outputs": _collect_workspace_outputs(runtime, session_id, case),
    }
    completed_result["score"] = _score_case(case, completed_result)
    return completed_result


def run_dataset(
    config_path: str | Path,
    dataset_path: str | Path,
    *,
    output_root: str | Path,
    run_name: str | None = None,
) -> Path:
    resolved_config = Path(config_path).expanduser().resolve()
    resolved_dataset = Path(dataset_path).expanduser().resolve()
    cases = load_dataset(resolved_dataset)
    run_dir = create_run_dir(output_root, run_name=run_name)

    shutil.copy2(resolved_config, run_dir / "config_snapshot.json")
    shutil.copy2(resolved_dataset, run_dir / "dataset_snapshot.jsonl")

    runtime = LocalAgentRuntime.from_config(
        config_path=resolved_config,
        store_dir=run_dir / "sessions",
        workspace_root_dir=run_dir / "workspaces",
    )

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] Running {case.id} ...", flush=True)
        result = run_case(runtime, case)
        results.append(result)
        (run_dir / "cases" / f"{case.id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    summary = _build_run_summary(
        run_dir=run_dir,
        config_path=resolved_config,
        dataset_path=resolved_dataset,
        results=results,
    )
    (run_dir / "run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_dir


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    run_dir = run_dataset(
        args.config,
        args.dataset,
        output_root=args.output_root,
        run_name=args.run_name,
    )
    print(f"Eval completed. Results saved to: {run_dir}")
    return 0


def _create_session_if_supported(
    runtime: LocalAgentRuntime,
    *,
    session_id: str,
    title: str,
) -> None:
    create_session = getattr(runtime, "create_session", None)
    if callable(create_session):
        try:
            create_session(session_id=session_id, title=title)
        except Exception:
            pass


def _prepare_workspace(
    runtime: LocalAgentRuntime,
    *,
    session_id: str,
    case: EvalCase,
) -> None:
    if not case.setup_files:
        return
    manager = runtime.workspace_manager
    if manager is None:
        raise RuntimeError("Eval case requires setup_files but this runtime has no workspace manager")

    workspace = manager.ensure_workspace(session_id)
    for item in case.setup_files:
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            raise ValueError(f"Eval case '{case.id}' has a setup_file with empty path")
        content = str(item.get("content", ""))
        resolved = (workspace / raw_path).resolve()
        try:
            resolved.relative_to(workspace.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Eval case '{case.id}' setup_file path '{raw_path}' is outside workspace",
            ) from exc
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8", newline="")


def _collect_workspace_outputs(
    runtime: LocalAgentRuntime,
    session_id: str,
    case: EvalCase,
) -> list[dict[str, Any]]:
    manager = runtime.workspace_manager
    if manager is None or not case.expected_files:
        return []

    workspace = manager.ensure_workspace(session_id)
    outputs: list[dict[str, Any]] = []
    for item in case.expected_files:
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            continue
        resolved = (workspace / raw_path).resolve()
        try:
            resolved.relative_to(workspace.resolve())
        except ValueError:
            outputs.append(
                {
                    "path": raw_path,
                    "exists": False,
                    "error": "outside workspace",
                },
            )
            continue
        payload: dict[str, Any] = {
            "path": raw_path,
            "exists": resolved.exists(),
        }
        if resolved.exists():
            payload["is_file"] = resolved.is_file()
            if resolved.is_file():
                try:
                    payload["content"] = resolved.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    payload["content"] = None
                    payload["encoding"] = "binary_or_non_utf8"
        outputs.append(payload)
    return outputs


def _build_run_summary(
    *,
    run_dir: Path,
    config_path: Path,
    dataset_path: Path,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = sum(1 for item in results if item["status"] == "completed")
    failed = sum(1 for item in results if item["status"] == "failed")
    scored_pass = sum(1 for item in results if bool(item.get("score", {}).get("pass")))
    scored_fail = len(results) - scored_pass
    category_summary = _build_category_summary(results)
    return {
        "run_id": run_dir.name,
        "dataset": dataset_path.name,
        "config": config_path.name,
        "case_count": len(results),
        "completed": completed,
        "failed": failed,
        "scored_pass": scored_pass,
        "scored_fail": scored_fail,
        "pass_rate": round(scored_pass / len(results), 4) if results else 0.0,
        "categories": category_summary,
        "cases": [
            {
                "id": item["id"],
                "status": item["status"],
                "category": item["category"],
                "pass": bool(item.get("score", {}).get("pass")),
            }
            for item in results
        ],
    }


def _score_case(case: EvalCase, result: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    if result.get("status") != "completed":
        checks.append(
            {
                "name": "execution_completed",
                "passed": False,
                "message": result.get("error", "case did not complete"),
            },
        )
        return {
            "pass": False,
            "passed_checks": 0,
            "failed_checks": 1,
            "checks": checks,
        }

    content = str(result.get("content") or "")
    tools_used = [str(item) for item in result.get("tools_used", [])]
    workspace_outputs = result.get("workspace_outputs", [])

    for expected in case.expected_contains:
        checks.append(
            {
                "name": "expected_contains",
                "target": expected,
                "passed": expected in content,
                "message": (
                    f"response contains '{expected}'"
                    if expected in content
                    else f"response is missing '{expected}'"
                ),
            },
        )

    for forbidden in case.forbidden_contains:
        checks.append(
            {
                "name": "forbidden_contains",
                "target": forbidden,
                "passed": forbidden not in content,
                "message": (
                    f"response does not contain forbidden text '{forbidden}'"
                    if forbidden not in content
                    else f"response contains forbidden text '{forbidden}'"
                ),
            },
        )

    for tool_name in case.expected_tools:
        checks.append(
            {
                "name": "expected_tool",
                "target": tool_name,
                "passed": tool_name in tools_used,
                "message": (
                    f"tool '{tool_name}' was used"
                    if tool_name in tools_used
                    else f"tool '{tool_name}' was not used"
                ),
            },
        )

    output_by_path = {
        str(item.get("path")): item for item in workspace_outputs if isinstance(item, dict)
    }
    for expected_file in case.expected_files:
        raw_path = str(expected_file.get("path", "")).strip()
        if not raw_path:
            continue
        output = output_by_path.get(raw_path)
        must_exist = bool(expected_file.get("must_exist", False))
        if must_exist:
            file_exists = bool(output and output.get("exists"))
            checks.append(
                {
                    "name": "expected_file_exists",
                    "target": raw_path,
                    "passed": file_exists,
                    "message": (
                        f"expected file '{raw_path}' exists"
                        if file_exists
                        else f"expected file '{raw_path}' does not exist"
                    ),
                },
            )

        content_contains = _coerce_list_of_strings(expected_file.get("content_contains"))
        file_content = ""
        if isinstance(output, dict) and isinstance(output.get("content"), str):
            file_content = output["content"]
        for expected_text in content_contains:
            checks.append(
                {
                    "name": "expected_file_content_contains",
                    "target": raw_path,
                    "value": expected_text,
                    "passed": expected_text in file_content,
                    "message": (
                        f"file '{raw_path}' contains '{expected_text}'"
                        if expected_text in file_content
                        else f"file '{raw_path}' is missing '{expected_text}'"
                    ),
                },
            )

    passed_checks = sum(1 for item in checks if item["passed"])
    failed_checks = sum(1 for item in checks if not item["passed"])
    return {
        "pass": failed_checks == 0,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "checks": checks,
    }


def _build_category_summary(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for item in results:
        category = str(item.get("category", "uncategorized"))
        bucket = summary.setdefault(
            category,
            {"total": 0, "completed": 0, "failed": 0, "passed": 0, "failed_score": 0},
        )
        bucket["total"] += 1
        if item.get("status") == "completed":
            bucket["completed"] += 1
        else:
            bucket["failed"] += 1
        if bool(item.get("score", {}).get("pass")):
            bucket["passed"] += 1
        else:
            bucket["failed_score"] += 1
    return summary


def _coerce_list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _coerce_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


if __name__ == "__main__":
    raise SystemExit(main())

"""LLM-as-judge utilities for eval runs."""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime
import json
from mimetypes import guess_type
import os
from pathlib import Path
import re
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openai import AsyncOpenAI

from simplified_chatbot.config.loader import load_env_for_config
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager

JUDGE_SYSTEM_PROMPT = """You are an eval judge for agent tasks.

Your job is to determine whether the agent completed the task correctly,
based only on the provided task description and evidence.

Rules:
- Judge the result, not the style.
- Do not require one exact command sequence or one exact interaction path.
- Use the task prompt as the main source of truth for what counts as success.
- Use artifacts, screenshots, final notes, and other provided evidence to determine whether the task was completed.
- If the evidence clearly supports success, return pass=true.
- If the evidence clearly shows failure, return pass=false.
- If the evidence is incomplete or ambiguous, return pass=false.
- Be concise and specific.

Return only valid JSON with this shape:
{
  "pass": true,
  "score": 0.95,
  "reason": "short explanation",
  "evidence_used": ["artifacts/final_notes.txt", "artifacts/final.png"]
}
"""

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_TEXT_PREVIEW_LIMIT = 8_000


@dataclass(slots=True)
class JudgeEvidence:
    """Normalized evidence packet for one case."""

    case_id: str
    category: str
    task_prompt: str
    assistant_answer: str
    skill_context: str | None
    text_artifacts: list[dict[str, str]]
    image_artifacts: list[dict[str, str]]
    trace_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "task_prompt": self.task_prompt,
            "assistant_answer": self.assistant_answer,
            "skill_context": self.skill_context,
            "text_artifacts": self.text_artifacts,
            "image_artifacts": self.image_artifacts,
            "trace_summary": self.trace_summary,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run LLM-as-judge over one eval run directory.",
    )
    parser.add_argument("config", help="Path to chatbot config JSON.")
    parser.add_argument("run_dir", help="Path to one eval run directory.")
    parser.add_argument(
        "--judge-model",
        default=os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4.1-mini"),
        help="Judge model name. Defaults to OPENAI_JUDGE_MODEL or gpt-4.1-mini.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Optional maximum number of completed cases to judge.",
    )
    parser.add_argument(
        "--detail",
        choices=["low", "high", "auto"],
        default="high",
        help="Image detail level for screenshot judging.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Optional case id filter. Can be passed multiple times.",
    )
    return parser


def load_case_results(run_dir: str | Path) -> list[dict[str, Any]]:
    cases_dir = Path(run_dir).expanduser().resolve() / "cases"
    if not cases_dir.exists():
        raise FileNotFoundError(f"Cases directory not found: {cases_dir}")
    results: list[dict[str, Any]] = []
    for case_file in sorted(cases_dir.glob("*.json")):
        payload = json.loads(case_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            results.append(payload)
    if not results:
        raise ValueError(f"No case result files found under: {cases_dir}")
    return results


def build_judge_evidence(run_dir: str | Path, case_result: dict[str, Any]) -> JudgeEvidence:
    run_path = Path(run_dir).expanduser().resolve()
    session_id = str(case_result.get("session_id", "")).strip()
    workspace_root = run_path / "workspaces" / SessionWorkspaceManager.safe_name(session_id)
    workspace_outputs = case_result.get("workspace_outputs", [])
    if not isinstance(workspace_outputs, list):
        workspace_outputs = []
    trace_summary = _summarize_events(case_result.get("events", []))
    category = str(case_result.get("category", "uncategorized"))
    skill_context = None
    if _should_include_agent_browser_skill(category=category, trace_summary=trace_summary):
        skill_context = _load_agent_browser_skill()

    text_artifacts: list[dict[str, str]] = []
    image_artifacts: list[dict[str, str]] = []

    for item in workspace_outputs:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).strip()
        if not raw_path or not bool(item.get("exists")):
            continue
        actual_path = workspace_root / raw_path
        ext = actual_path.suffix.lower()
        if ext in _IMAGE_EXTS and actual_path.exists():
            image_artifacts.append(
                {
                    "path": raw_path,
                    "absolute_path": str(actual_path.resolve()),
                },
            )
            continue
        content = item.get("content")
        if isinstance(content, str):
            preview = content[:_TEXT_PREVIEW_LIMIT]
            if len(content) > _TEXT_PREVIEW_LIMIT:
                preview += "\n\n(Output truncated)"
            text_artifacts.append(
                {
                    "path": raw_path,
                    "content": preview,
                },
            )

    return JudgeEvidence(
        case_id=str(case_result.get("id", "")),
        category=category,
        task_prompt=str(case_result.get("prompt", "")),
        assistant_answer=str(case_result.get("content", "")),
        skill_context=skill_context,
        text_artifacts=text_artifacts,
        image_artifacts=image_artifacts,
        trace_summary=trace_summary,
    )


def render_judge_text_packet(evidence: JudgeEvidence) -> str:
    lines = [
        "[Task]",
        evidence.task_prompt or "(missing)",
        "",
        "[Category]",
        evidence.category or "uncategorized",
        "",
        "[Agent Final Answer]",
        evidence.assistant_answer or "(empty)",
        "",
    ]

    if evidence.skill_context:
        lines.extend(
            [
                "[Relevant Skill Rules]",
                evidence.skill_context,
                "",
            ],
        )

    lines.append("[Artifacts]")

    if evidence.text_artifacts:
        for item in evidence.text_artifacts:
            lines.extend(
                [
                    f"- {item['path']}",
                    item["content"],
                    "",
                ],
            )
    else:
        lines.append("(No text artifacts)")
        lines.append("")

    lines.append("[Available Image Artifacts]")
    if evidence.image_artifacts:
        for item in evidence.image_artifacts:
            lines.append(f"- {item['path']}")
    else:
        lines.append("(No image artifacts)")
    lines.append("")

    lines.extend(
        [
            "[Trace Summary]",
            json.dumps(evidence.trace_summary, ensure_ascii=False, indent=2),
        ],
    )
    return "\n".join(lines).strip()


def image_file_to_data_url(path: str | Path) -> str:
    file_path = Path(path).expanduser().resolve()
    mime_type = guess_type(file_path.name)[0] or "image/png"
    encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


async def judge_case_async(
    client: AsyncOpenAI,
    *,
    evidence: JudgeEvidence,
    model: str,
    detail: str = "high",
) -> dict[str, Any]:
    content_items: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": render_judge_text_packet(evidence),
        },
    ]
    for item in evidence.image_artifacts:
        content_items.append(
            {
                "type": "input_image",
                "image_url": image_file_to_data_url(item["absolute_path"]),
                "detail": detail,
            },
        )

    response = await client.responses.create(
        model=model,
        instructions=JUDGE_SYSTEM_PROMPT,
        input=[
            {
                "role": "user",
                "content": content_items,
            },
        ],
    )
    raw_output = response.output_text
    verdict = parse_judge_output(raw_output)
    return {
        "case_id": evidence.case_id,
        "judge_model": model,
        "verdict": verdict,
        "raw_output": raw_output,
        "evidence": evidence.to_dict(),
    }


def parse_judge_output(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if match is None:
        raise ValueError("Judge output did not contain a JSON object")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("Judge output JSON must be an object")
    return payload


async def judge_run_async(
    config_path: str | Path,
    run_dir: str | Path,
    *,
    judge_model: str,
    detail: str = "high",
    max_cases: int | None = None,
    case_ids: set[str] | None = None,
) -> Path:
    load_env_for_config(config_path)
    run_path = Path(run_dir).expanduser().resolve()
    case_results = load_case_results(run_path)
    if case_ids:
        case_results = [item for item in case_results if str(item.get("id")) in case_ids]
    case_results = [item for item in case_results if item.get("status") == "completed"]
    if max_cases is not None:
        case_results = case_results[:max_cases]
    if not case_results:
        raise ValueError("No completed cases matched the requested filters")

    output_dir = _create_judge_output_dir(run_path)
    client = AsyncOpenAI()
    judgments: list[dict[str, Any]] = []

    for index, case_result in enumerate(case_results, start=1):
        case_id = str(case_result.get("id", "unknown"))
        print(f"[{index}/{len(case_results)}] Judging {case_id} ...", flush=True)
        evidence = build_judge_evidence(run_path, case_result)
        judgment = await judge_case_async(
            client,
            evidence=evidence,
            model=judge_model,
            detail=detail,
        )
        judgments.append(judgment)
        (output_dir / "cases" / f"{case_id}.json").write_text(
            json.dumps(judgment, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    summary = _build_judge_summary(
        run_dir=run_path,
        judge_dir=output_dir,
        judge_model=judge_model,
        judgments=judgments,
    )
    (output_dir / "run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_dir


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    output_dir = asyncio.run(
        judge_run_async(
            args.config,
            args.run_dir,
            judge_model=args.judge_model,
            detail=args.detail,
            max_cases=args.max_cases,
            case_ids=set(args.case_id) if args.case_id else None,
        ),
    )
    print(f"LLM judge completed. Results saved to: {output_dir}")
    return 0


def _create_judge_output_dir(run_dir: Path) -> Path:
    root = run_dir / "llm_judgments"
    root.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    candidate = root / base
    suffix = 2
    while candidate.exists():
        candidate = root / f"{base}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    (candidate / "cases").mkdir(parents=True, exist_ok=True)
    return candidate


def _summarize_events(events: Any) -> dict[str, Any]:
    if not isinstance(events, list):
        return {
            "event_count": 0,
            "exec_command_count": 0,
            "agent_browser_command_count": 0,
            "agent_browser_commands": [],
        }

    exec_commands: list[str] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        if item.get("event") != "tool_call_started":
            continue
        data = item.get("data")
        if not isinstance(data, dict) or data.get("name") != "exec":
            continue
        arguments = data.get("arguments")
        if not isinstance(arguments, dict):
            continue
        command = arguments.get("command")
        if isinstance(command, str) and command.strip():
            exec_commands.append(command)

    agent_browser_commands = [cmd for cmd in exec_commands if "agent-browser" in cmd]
    return {
        "event_count": len(events),
        "exec_command_count": len(exec_commands),
        "agent_browser_command_count": len(agent_browser_commands),
        "agent_browser_commands": agent_browser_commands[:10],
    }


def _build_judge_summary(
    *,
    run_dir: Path,
    judge_dir: Path,
    judge_model: str,
    judgments: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = 0
    failed = 0
    for item in judgments:
        verdict = item.get("verdict", {})
        if isinstance(verdict, dict) and bool(verdict.get("pass")):
            passed += 1
        else:
            failed += 1
    return {
        "source_run": run_dir.name,
        "judge_run": judge_dir.name,
        "judge_model": judge_model,
        "case_count": len(judgments),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(judgments), 4) if judgments else 0.0,
        "cases": [
            {
                "case_id": item.get("case_id"),
                "pass": bool(item.get("verdict", {}).get("pass")) if isinstance(item.get("verdict"), dict) else False,
                "score": item.get("verdict", {}).get("score") if isinstance(item.get("verdict"), dict) else None,
            }
            for item in judgments
        ],
    }


def _should_include_agent_browser_skill(
    *,
    category: str,
    trace_summary: dict[str, Any],
) -> bool:
    if category == "browser_cli":
        return True
    return int(trace_summary.get("agent_browser_command_count", 0)) > 0


def _load_agent_browser_skill() -> str | None:
    skill_path = (
        PROJECT_ROOT
        / "simplified_chatbot"
        / "skills"
        / "builtins"
        / "agent-browser"
        / "SKILL.md"
    )
    if not skill_path.exists():
        return None
    return skill_path.read_text(encoding="utf-8").strip()


if __name__ == "__main__":
    raise SystemExit(main())

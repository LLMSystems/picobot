"""TodoWrite tool for managing a structured task list within a session."""

from __future__ import annotations

from typing import Any, Literal

from simplified_chatbot.tools.base import Tool, tool_parameters

TodoStatus = Literal["pending", "in_progress", "completed"]


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "The updated todo list (replaces the entire current list).",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Imperative description of the task (e.g. 'Run tests').",
                            "minLength": 1,
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present-continuous form shown while in progress (e.g. 'Running tests').",
                            "minLength": 1,
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Current status of the task.",
                        },
                    },
                    "required": ["content", "activeForm", "status"],
                },
            },
        },
        "required": ["todos"],
    },
)
class TodoWriteTool(Tool):
    """Manage a structured task list for the current session.

    Each call replaces the entire todo list. Exactly one task should be
    in_progress at a time. Mark tasks completed immediately after finishing.
    """

    def __init__(self) -> None:
        self._todos: list[dict[str, str]] = []

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "Create and manage a structured task list for the current session. "
            "Each call replaces the entire list. "
            "Use status 'pending' for not-yet-started tasks, 'in_progress' for the "
            "one task currently being worked on (only one at a time), and 'completed' "
            "for finished tasks. "
            "Call this proactively for any task with 3+ steps."
        )

    async def execute(self, todos: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        in_progress = [t for t in todos if t.get("status") == "in_progress"]
        if len(in_progress) > 1:
            names = ", ".join(f'"{t["content"]}"' for t in in_progress)
            return {"ok": False, "error": f"Only one task may be in_progress at a time. Found: {names}"}

        self._todos = [
            {
                "content": str(t.get("content", "")),
                "activeForm": str(t.get("activeForm", "")),
                "status": str(t.get("status", "pending")),
            }
            for t in todos
        ]

        total = len(self._todos)
        done = sum(1 for t in self._todos if t["status"] == "completed")
        return {
            "ok": True,
            "todos": self._todos,
            "completed": done,
            "total": total,
        }

    def get_todos(self) -> list[dict[str, str]]:
        """Return a copy of the current todo list."""
        return list(self._todos)

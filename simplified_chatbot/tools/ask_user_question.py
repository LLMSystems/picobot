"""AskUserQuestion tool — pauses the agent loop to collect interactive user input."""

from __future__ import annotations

import asyncio
from typing import Any

from simplified_chatbot.tools.base import Tool, tool_parameters

_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Display text for the option."},
        "description": {"type": "string", "description": "Brief explanation of the option."},
    },
    "required": ["label", "description"],
}

_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The question to ask the user."},
        "header": {
            "type": "string",
            "description": "Short label (max 12 chars) shown as a chip tag.",
        },
        "multiSelect": {
            "type": "boolean",
            "description": "Whether the user may select multiple options.",
        },
        "options": {
            "type": "array",
            "items": _OPTION_SCHEMA,
            "minItems": 2,
            "maxItems": 4,
            "description": "Available choices (2-4 options).",
        },
    },
    "required": ["question", "header", "options", "multiSelect"],
}


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": _QUESTION_SCHEMA,
                "minItems": 1,
                "maxItems": 4,
                "description": "List of 1-4 questions to ask the user.",
            },
        },
        "required": ["questions"],
    },
)
class AskUserQuestionTool(Tool):
    """Pause the agent and ask the user one or more clarifying questions.

    The agent loop suspends until the user submits answers via the chat UI.
    Use only when the task cannot proceed without user input.
    """

    _DEFAULT_TIMEOUT_SECONDS = 600  # 10 minutes

    def __init__(self, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout
        self._pending: asyncio.Future[dict[str, Any]] | None = None

    @property
    def name(self) -> str:
        return "ask_user_question"

    @property
    def description(self) -> str:
        return (
            "Pause the current task and ask the user 1-4 clarifying questions. "
            "Each question must have 2-4 multiple-choice options. "
            "The agent loop suspends until the user submits answers. "
            "Use only when the task genuinely cannot proceed without the user's input."
        )

    @property
    def has_pending(self) -> bool:
        """True if a question is currently awaiting a user answer."""
        return self._pending is not None and not self._pending.done()

    async def execute(self, questions: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
        if self._pending is not None and not self._pending.done():
            return {"ok": False, "error": "A question is already pending for this session."}

        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        try:
            answers = await asyncio.wait_for(
                asyncio.shield(self._pending),
                timeout=self._timeout,
            )
            return {"ok": True, "answers": answers}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Timed out waiting for user response."}
        finally:
            self._pending = None

    def answer(self, answers: dict[str, Any]) -> bool:
        """Deliver the user's answers and resume the agent loop.

        Returns True if a pending question was resolved, False otherwise.
        """
        if self._pending is None or self._pending.done():
            return False
        self._pending.set_result(answers)
        return True

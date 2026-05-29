"""Per-session workspace helpers for local runtime."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from simplified_chatbot.skills.loader import SkillsLoader


class SessionWorkspaceManager:
    """Map session ids to isolated local workspace directories."""

    _SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")

    def __init__(
        self,
        root_dir: str | Path,
        skills_loader: SkillsLoader | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._skills_loader = skills_loader

    @classmethod
    def safe_name(cls, session_id: str) -> str:
        normalized = cls._SAFE_RE.sub("_", session_id.strip())
        normalized = normalized.strip("._")
        return normalized or "session"

    def path_for(self, session_id: str) -> Path:
        return self.root_dir / self.safe_name(session_id)

    def ensure_workspace(self, session_id: str) -> Path:
        workspace = self.path_for(session_id)
        workspace.mkdir(parents=True, exist_ok=True)
        if self._skills_loader is not None:
            self._skills_loader.copy_to_workspace(workspace)
        return workspace

    def delete_workspace(self, session_id: str) -> None:
        workspace = self.path_for(session_id)
        if workspace.exists():
            shutil.rmtree(workspace)

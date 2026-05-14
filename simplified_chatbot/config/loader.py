"""Load and save simplified chatbot config files."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from simplified_chatbot.config.schema import ChatbotConfig

_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def default_config_path() -> Path:
    """Return the default config path used when none is provided."""
    return Path.cwd() / "config.json"


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    """Return an expanded absolute config path."""
    raw = default_config_path() if config_path is None else Path(config_path)
    return raw.expanduser().resolve()


def load_config(config_path: str | Path | None = None) -> ChatbotConfig:
    """Load and validate a config file."""
    path = resolve_config_path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    _load_dotenv_for_path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    resolved = _resolve_env_vars(data)
    return ChatbotConfig.model_validate(resolved)


def save_config(
    config: ChatbotConfig,
    config_path: str | Path | None = None,
) -> Path:
    """Save a config object to disk."""
    path = resolve_config_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _resolve_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF_PATTERN.sub(_replace_env_var, value)
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_env_vars(item) for key, item in value.items()}
    return value


def _replace_env_var(match: re.Match[str]) -> str:
    name = match.group(1)
    env_value = os.environ.get(name)
    if env_value is None:
        raise ValueError(
            f"Environment variable '{name}' referenced in config is not set",
        )
    return env_value


def _load_dotenv_for_path(config_path: Path) -> None:
    dotenv_path = _find_dotenv(config_path.parent)
    if dotenv_path is None or not dotenv_path.exists():
        return
    for name, value in _parse_dotenv(dotenv_path).items():
        os.environ.setdefault(name, value)


def _find_dotenv(start_dir: Path) -> Path | None:
    current = start_dir.resolve()
    while True:
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _parse_dotenv(dotenv_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        key = name.strip()
        if not key:
            continue
        values[key] = _strip_dotenv_value(raw_value.strip())
    return values


def _strip_dotenv_value(raw_value: str) -> str:
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'"', "'"}:
        return raw_value[1:-1]
    return raw_value

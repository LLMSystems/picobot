"""Alert rule schema + YAML loader.

Rules live in `alerts.yaml` at the repo root; the schema is validated up-front
so a malformed file fails server startup rather than silently producing dead
rules at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, field_validator

try:
    import yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - pyyaml ships in pyproject
    yaml = None  # type: ignore[assignment]


Severity = Literal["info", "warning", "critical"]

# Thresholds may be numeric or boolean (e.g. `chrome_alive == false`).
ThresholdValue = Union[float, int, bool]

_VALID_COMPARATORS = {">", ">=", "<", "<=", "==", "!="}


class AlertRule(BaseModel):
    """One configured alert rule."""

    name: str = Field(min_length=1, description="Unique rule identifier (snake_case)")
    display_name: str | None = Field(
        default=None,
        description="Optional human-readable label (e.g. localised) — UI falls back to `name` when omitted",
    )
    description: str = Field(min_length=1, description="Human-readable summary")
    severity: Severity = "warning"
    metric_path: str = Field(
        min_length=1,
        description="Dotted path into the snapshot, e.g. 'system.cpu_percent'",
    )
    comparator: str = Field(default=">", description="One of > >= < <= == !=")
    threshold: ThresholdValue
    for_seconds: int = Field(
        default=0,
        ge=0,
        description="Condition must hold continuously for N seconds before firing",
    )
    enabled: bool = True

    @field_validator("comparator")
    @classmethod
    def _validate_comparator(cls, v: str) -> str:
        if v not in _VALID_COMPARATORS:
            raise ValueError(
                f"comparator must be one of {sorted(_VALID_COMPARATORS)}",
            )
        return v

    def evaluate(self, value: Any) -> bool:
        """True if `value` satisfies this rule's comparator-threshold test."""
        if value is None:
            return False
        threshold = self.threshold
        # Boolean threshold: only support equality / inequality.
        if isinstance(threshold, bool):
            if self.comparator == "==":
                return value == threshold
            if self.comparator == "!=":
                return value != threshold
            return False
        # Numeric: coerce defensively, treat non-numeric values as not-matching.
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return False
        numeric_threshold = float(threshold)
        if self.comparator == ">":
            return numeric_value > numeric_threshold
        if self.comparator == ">=":
            return numeric_value >= numeric_threshold
        if self.comparator == "<":
            return numeric_value < numeric_threshold
        if self.comparator == "<=":
            return numeric_value <= numeric_threshold
        if self.comparator == "==":
            return numeric_value == numeric_threshold
        if self.comparator == "!=":
            return numeric_value != numeric_threshold
        return False


class AlertConfig(BaseModel):
    """Top-level alerts.yaml schema."""

    rules: list[AlertRule] = Field(default_factory=list)

    @field_validator("rules")
    @classmethod
    def _unique_names(cls, rules: list[AlertRule]) -> list[AlertRule]:
        seen: set[str] = set()
        for r in rules:
            if r.name in seen:
                raise ValueError(f"duplicate rule name: {r.name}")
            seen.add(r.name)
        return rules


def load_rules(path: str | Path | None) -> list[AlertRule]:
    """Load and validate the rules YAML. Returns [] if path is falsy or missing.

    Raises ValueError (with a pydantic-style message) on schema errors.
    """
    if not path:
        return []
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return []
    if yaml is None:
        raise RuntimeError(
            "pyyaml not installed; run `pip install pyyaml` to load alert rules",
        )
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    config = AlertConfig.model_validate(raw)
    return [r for r in config.rules if r.enabled]


def resolve_metric_value(snapshot: dict[str, Any], path: str) -> Any:
    """Walk `snapshot` along `path` ('a.b.c'); return None if anything missing."""
    cur: Any = snapshot
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur

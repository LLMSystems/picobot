"""Tests for the alert rule schema + YAML loader."""

from __future__ import annotations

import pytest

from simplified_chatbot.alerts.rules import (
    AlertRule,
    load_rules,
    resolve_metric_value,
)


def test_alert_rule_evaluates_numeric_comparators():
    rule = AlertRule(
        name="cpu_high",
        description="CPU > 80",
        metric_path="system.cpu_percent",
        comparator=">",
        threshold=80,
    )
    assert rule.evaluate(90.0) is True
    assert rule.evaluate(80.0) is False
    assert rule.evaluate(None) is False


def test_alert_rule_evaluates_boolean_equality():
    rule = AlertRule(
        name="chrome_down",
        description="chrome stopped",
        metric_path="system.chrome_alive",
        comparator="==",
        threshold=False,
    )
    assert rule.evaluate(False) is True
    assert rule.evaluate(True) is False
    # None should never satisfy a rule.
    assert rule.evaluate(None) is False


def test_alert_rule_rejects_invalid_comparator():
    with pytest.raises(Exception):
        AlertRule(
            name="bad",
            description="bad",
            metric_path="x.y",
            comparator="??",
            threshold=1,
        )


def test_resolve_metric_value_walks_nested_dict():
    snap = {"system": {"cpu_percent": 12.3, "nested": {"a": 1}}}
    assert resolve_metric_value(snap, "system.cpu_percent") == 12.3
    assert resolve_metric_value(snap, "system.nested.a") == 1
    assert resolve_metric_value(snap, "system.missing") is None
    assert resolve_metric_value(snap, "no.such.path") is None


def test_load_rules_returns_empty_when_path_missing(tmp_path):
    assert load_rules(tmp_path / "nope.yaml") == []


def test_load_rules_parses_valid_yaml(tmp_path):
    yaml_path = tmp_path / "alerts.yaml"
    yaml_path.write_text(
        """
rules:
  - name: a
    description: A
    severity: warning
    metric_path: system.cpu_percent
    comparator: ">"
    threshold: 80
  - name: b
    description: B
    severity: critical
    metric_path: api.error_5xx_rate_1h
    comparator: ">"
    threshold: 0.05
    for_seconds: 60
""".strip(),
        encoding="utf-8",
    )
    rules = load_rules(yaml_path)
    assert [r.name for r in rules] == ["a", "b"]
    assert rules[1].for_seconds == 60


def test_load_rules_rejects_duplicate_names(tmp_path):
    yaml_path = tmp_path / "alerts.yaml"
    yaml_path.write_text(
        """
rules:
  - name: a
    description: x
    metric_path: foo.bar
    comparator: ">"
    threshold: 1
  - name: a
    description: y
    metric_path: foo.bar
    comparator: ">"
    threshold: 2
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        load_rules(yaml_path)


def test_load_rules_skips_disabled(tmp_path):
    yaml_path = tmp_path / "alerts.yaml"
    yaml_path.write_text(
        """
rules:
  - name: enabled
    description: x
    metric_path: foo.bar
    comparator: ">"
    threshold: 1
  - name: turned_off
    description: y
    metric_path: foo.bar
    comparator: ">"
    threshold: 2
    enabled: false
""".strip(),
        encoding="utf-8",
    )
    rules = load_rules(yaml_path)
    assert [r.name for r in rules] == ["enabled"]

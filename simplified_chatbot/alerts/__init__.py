"""Alerting layer — rule-based detection over the metrics snapshot.

Public surface:
- `AlertRule` / `load_rules()` — config models and YAML loader
- `AlertService` — orchestrates evaluation + persistence + state
"""

from simplified_chatbot.alerts.rules import AlertRule, Severity, load_rules
from simplified_chatbot.alerts.service import AlertService

__all__ = ["AlertRule", "AlertService", "Severity", "load_rules"]

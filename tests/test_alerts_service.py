"""Tests for AlertService state machine and events_store."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiosqlite")

from simplified_chatbot.alerts.events_store import AlertEventsStore
from simplified_chatbot.alerts.rules import AlertRule
from simplified_chatbot.alerts.service import AlertService


def _build_service(tmp_path, rules: list[AlertRule]) -> AlertService:
    return AlertService(
        store=AlertEventsStore(tmp_path / "alerts.db"),
        rules=rules,
    )


def _cpu_rule(threshold: float = 80, for_seconds: int = 0) -> AlertRule:
    return AlertRule(
        name="cpu_high",
        description="cpu",
        severity="warning",
        metric_path="system.cpu_percent",
        comparator=">",
        threshold=threshold,
        for_seconds=for_seconds,
    )


def test_evaluate_fires_when_condition_first_satisfied(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        result = await svc.evaluate({"system": {"cpu_percent": 90}})
        assert len(result.fired) == 1
        assert result.fired[0].rule_name == "cpu_high"
        assert result.resolved == []
        active = await svc.list_active()
        assert len(active) == 1

    asyncio.run(run())


def test_evaluate_does_not_double_fire(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        await svc.evaluate({"system": {"cpu_percent": 90}})
        result = await svc.evaluate({"system": {"cpu_percent": 91}})
        assert result.fired == []
        assert result.resolved == []
        assert len(await svc.list_active()) == 1

    asyncio.run(run())


def test_evaluate_resolves_when_condition_clears(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        await svc.evaluate({"system": {"cpu_percent": 90}})
        result = await svc.evaluate({"system": {"cpu_percent": 50}})
        assert len(result.resolved) == 1
        assert result.resolved[0].rule_name == "cpu_high"
        assert result.resolved[0].resolved_at is not None
        assert await svc.list_active() == []

    asyncio.run(run())


def test_evaluate_refires_after_resolution(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        await svc.evaluate({"system": {"cpu_percent": 90}})  # fire
        await svc.evaluate({"system": {"cpu_percent": 50}})  # resolve
        result = await svc.evaluate({"system": {"cpu_percent": 95}})  # fire again
        assert len(result.fired) == 1
        history = await svc.list_history()
        assert len(history) == 2

    asyncio.run(run())


def test_for_seconds_dampens_first_fire(tmp_path):
    rule = _cpu_rule(for_seconds=10)
    svc = _build_service(tmp_path, [rule])

    async def run():
        # First eval at t=0 — condition met but for_seconds not elapsed → no fire.
        r1 = await svc.evaluate({"system": {"cpu_percent": 90}})
        assert r1.fired == []
        # Backdate the pending timer so for_seconds appears satisfied.
        svc._pending["cpu_high"].condition_true_since -= 20
        r2 = await svc.evaluate({"system": {"cpu_percent": 90}})
        assert len(r2.fired) == 1

    asyncio.run(run())


def test_silence_blocks_firing(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        await svc.silence(rule_name="cpu_high", until_iso="2999-01-01T00:00:00+00:00")
        result = await svc.evaluate({"system": {"cpu_percent": 95}})
        assert result.fired == []
        assert await svc.list_active() == []

    asyncio.run(run())


def test_acknowledge_marks_event(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        result = await svc.evaluate({"system": {"cpu_percent": 90}})
        event_id = result.fired[0].id
        ok = await svc.acknowledge(event_id)
        assert ok is True
        # Second ack is a no-op.
        ok2 = await svc.acknowledge(event_id)
        assert ok2 is False

    asyncio.run(run())


def test_hydrate_from_db_restores_active_event_id(tmp_path):
    rule = _cpu_rule()
    store = AlertEventsStore(tmp_path / "alerts.db")

    async def run() -> int:
        svc1 = AlertService(store=store, rules=[rule])
        result = await svc1.evaluate({"system": {"cpu_percent": 90}})
        event_id = result.fired[0].id

        # Simulate restart by building a fresh service with the same store.
        svc2 = AlertService(store=store, rules=[rule])
        await svc2.hydrate_from_db()
        assert svc2._pending["cpu_high"].active_event_id == event_id
        # The rehydrated service should not re-fire on the same condition.
        result2 = await svc2.evaluate({"system": {"cpu_percent": 90}})
        assert result2.fired == []
        return event_id

    asyncio.run(run())


def test_missing_metric_does_not_fire(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run():
        result = await svc.evaluate({"system": {}})  # cpu_percent missing
        assert result.fired == []
        # And nothing weird in active list.
        assert await svc.list_active() == []

    asyncio.run(run())


def test_subscribe_receives_fire_and_resolve_events(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run() -> list[dict]:
        queue = svc.subscribe()
        await svc.evaluate({"system": {"cpu_percent": 90}})
        await svc.evaluate({"system": {"cpu_percent": 50}})
        events: list[dict] = []
        # Drain whatever the broadcast deposited.
        while not queue.empty():
            events.append(queue.get_nowait())
        svc.unsubscribe(queue)
        return events

    events = asyncio.run(run())
    names = [e["event"] for e in events]
    assert names == ["alert_fired", "alert_resolved"]
    assert events[0]["data"]["rule_name"] == "cpu_high"


def test_subscribe_receives_ack_and_silence_events(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run() -> list[str]:
        # Need a firing event first so ack has something to target.
        await svc.evaluate({"system": {"cpu_percent": 90}})
        queue = svc.subscribe()
        active = await svc.list_active()
        await svc.acknowledge(active[0].id)
        await svc.silence(rule_name="cpu_high", until_iso="2999-01-01T00:00:00+00:00")
        await svc.unsilence(rule_name="cpu_high")
        events: list[str] = []
        while not queue.empty():
            events.append(queue.get_nowait()["event"])
        svc.unsubscribe(queue)
        return events

    assert asyncio.run(run()) == [
        "alert_acknowledged",
        "alert_silenced",
        "alert_unsilenced",
    ]


def test_broadcast_drops_when_subscriber_queue_is_full(tmp_path):
    svc = _build_service(tmp_path, [_cpu_rule()])

    async def run() -> int:
        queue = svc.subscribe(maxsize=1)
        # First fire fills the queue.
        await svc.evaluate({"system": {"cpu_percent": 90}})
        # Resolve gets dropped silently — no exception leaks.
        await svc.evaluate({"system": {"cpu_percent": 50}})
        size = queue.qsize()
        svc.unsubscribe(queue)
        return size

    # Even though two events were emitted, the bounded queue keeps the first
    # and the second is dropped.
    assert asyncio.run(run()) == 1

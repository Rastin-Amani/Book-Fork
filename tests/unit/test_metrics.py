"""Lightweight metrics registry."""

from __future__ import annotations

from app.observability.metrics import Metrics


def test_counters_accumulate_and_render_prometheus() -> None:
    m = Metrics()
    m.inc("jobs_total")
    m.inc("jobs_total", 2)
    m.inc("provider_errors_total", 1, category="timeout")
    m.set("active_jobs", 3)

    snapshot = m.snapshot()
    assert snapshot["counters"]["jobs_total"] == 3.0
    assert snapshot["counters"]['provider_errors_total{category="timeout"}'] == 1.0
    assert snapshot["gauges"]["active_jobs"] == 3.0

    rendered = m.render_prometheus()
    assert "jobs_total 3.0" in rendered
    assert 'provider_errors_total{category="timeout"} 1.0' in rendered
    assert "active_jobs 3.0" in rendered


def test_reset_clears_registry() -> None:
    m = Metrics()
    m.inc("x")
    m.set("g", 1)
    m.reset()
    assert m.snapshot() == {"counters": {}, "gauges": {}}

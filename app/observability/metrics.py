"""Minimal in-process metrics.

Deliberately not a full observability stack: a thread-safe counter/gauge registry
with a Prometheus text exposition, good enough for a single instance or a few
replicas scraped independently. No external dependency.

Counters are monotonic; gauges are last-value. Labels are part of the series key.
``# ponytail: per-process metrics; aggregate at scrape time or move to a shared
registry when multi-replica accuracy matters``
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any


def _label_suffix(labels: dict[str, Any]) -> str:
    if not labels:
        return ""
    parts = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    return "{" + parts + "}"


class Metrics:
    """A small counter/gauge registry."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels: Any) -> None:
        key = f"{name}{_label_suffix(labels)}"
        with self._lock:
            self._counters[key] += value

    def set(self, name: str, value: float, **labels: Any) -> None:
        key = f"{name}{_label_suffix(labels)}"
        with self._lock:
            self._gauges[key] = float(value)

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {"counters": dict(self._counters), "gauges": dict(self._gauges)}

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {key.split('{')[0]} counter")
                lines.append(f"{key} {value}")
            for key, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {key.split('{')[0]} gauge")
                lines.append(f"{key} {value}")
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()


metrics = Metrics()

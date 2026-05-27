"""Shared Prometheus metrics for memrag-shared recall modules.

``prometheus_client`` is an optional dependency.  When it is not installed,
or when the metric has already been registered (e.g. in test environments that
run multiple modules in the same process), a lightweight no-op stub is used so
that recall modules never raise ``ImportError`` or ``ValueError`` at runtime.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator


# ---------------------------------------------------------------------------
# No-op stubs — always defined so they can be used as a fallback.
# ---------------------------------------------------------------------------


class _NoopLabelProxy:
    def observe(self, value: float) -> None:  # noqa: ARG002
        pass


class _NoopHistogram:
    def labels(self, **kw: str) -> _NoopLabelProxy:  # noqa: ARG002
        return _NoopLabelProxy()


# ---------------------------------------------------------------------------
# Try to load a real Prometheus Histogram; fall back to no-op on any error.
# ---------------------------------------------------------------------------

_DEFAULT_BUCKETS = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]

_recall_latency: object = None  # set on first call, then reused


def _get_recall_latency_histogram() -> object:
    """Return the singleton histogram (real or no-op).

    Lazy creation avoids registering the metric before the prometheus registry
    is ready and prevents duplicate-registration errors when multiple modules
    are imported in the same process (e.g. during pytest runs).
    """
    global _recall_latency
    if _recall_latency is not None:
        return _recall_latency

    try:
        from prometheus_client import Histogram  # type: ignore[import-untyped]

        _recall_latency = Histogram(
            "memory_recall_latency_seconds",
            "Wall-clock seconds for each layer recall function",
            labelnames=["layer", "workspace_id"],
            buckets=_DEFAULT_BUCKETS,
        )
    except Exception:
        # ImportError (not installed) or ValueError (already registered).
        # Fall back to a no-op so callers always get something with .labels().
        _recall_latency = _NoopHistogram()

    return _recall_latency


@contextmanager
def record_recall_latency(layer: str, workspace_id: str) -> Generator[None, None, None]:
    """Context manager that measures wall time and records to the histogram.

    Usage::

        async def recall_agent_memory(workspace_id, ...):
            with record_recall_latency("layer2", workspace_id):
                ...
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        _get_recall_latency_histogram().labels(  # type: ignore[union-attr]
            layer=layer, workspace_id=workspace_id
        ).observe(elapsed)


"""Capture statistics for telemetry (pure logic, no bpy).

Transport latency is measured as ``applied_monotonic_ms - packet.t`` where
``packet.t`` is the backend's epoch-ms send timestamp. Both clocks are on the
same machine, so skew is negligible for localhost capture; values are clamped
to >= 0 anyway.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from .schema import Packet

STATS_WINDOW = 120  # samples kept for avg/max latency


@dataclass
class CaptureStats:
    """Rolling per-session stats, read by the UI panel each redraw."""

    packets_applied: int = 0
    invalid_packets: int = 0
    packets_dropped_idle: int = 0  # polls that found no new packet
    applied_fps: float = 0.0
    avg_transport_ms: float = 0.0
    max_transport_ms: float = 0.0
    engine: str = ""
    _latency_window: deque = field(default_factory=lambda: deque(maxlen=STATS_WINDOW), repr=False)
    _applied_times: deque = field(default_factory=lambda: deque(maxlen=STATS_WINDOW), repr=False)

    def record_applied(self, packet: Packet, applied_monotonic_ms: float | None = None) -> None:
        if applied_monotonic_ms is None:
            applied_monotonic_ms = time.monotonic() * 1000.0
        transport_ms = max(0.0, applied_monotonic_ms - packet.t)

        self.packets_applied += 1
        self.engine = packet.engine
        self._latency_window.append(transport_ms)
        self._applied_times.append(applied_monotonic_ms)
        self._recompute()

    def record_invalid(self) -> None:
        self.invalid_packets += 1

    def record_idle_poll(self) -> None:
        self.packets_dropped_idle += 1

    def _recompute(self) -> None:
        if self._latency_window:
            self.avg_transport_ms = sum(self._latency_window) / len(self._latency_window)
            self.max_transport_ms = max(self._latency_window)
        if len(self._applied_times) >= 2:
            span_s = (self._applied_times[-1] - self._applied_times[0]) / 1000.0
            if span_s > 0:
                self.applied_fps = (len(self._applied_times) - 1) / span_s

    def reset(self) -> None:
        self.packets_applied = 0
        self.invalid_packets = 0
        self.packets_dropped_idle = 0
        self.applied_fps = 0.0
        self.avg_transport_ms = 0.0
        self.max_transport_ms = 0.0
        self.engine = ""
        self._latency_window.clear()
        self._applied_times.clear()

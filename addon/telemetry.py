"""Capture statistics for telemetry (pure logic, no bpy).

Two clocks, two purposes:
- FPS is a rate: it stays on the monotonic clock (``_applied_times``).
- Transport latency is a difference against a sender-supplied wall-clock
  stamp: ``packet.t`` is epoch ms, so it must be subtracted from the applied
  time on the SAME epoch clock (``time.time()``). Comparing epoch ms against
  monotonic ms always goes negative and clamps to exactly 0.0.
Replay passes the packet's own stamp as the applied epoch time so replayed
packets report zero latency by intent, not because of a clock mismatch.
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

    def record_applied(
        self,
        packet: Packet,
        applied_monotonic_ms: float | None = None,
        applied_epoch_ms: float | None = None,
    ) -> None:
        """Record one applied packet.

        ``applied_monotonic_ms`` feeds FPS (a rate). ``applied_epoch_ms`` must
        be on the same epoch clock as ``packet.t`` and feeds transport latency.
        """
        if applied_monotonic_ms is None:
            applied_monotonic_ms = time.monotonic() * 1000.0
        if applied_epoch_ms is None:
            applied_epoch_ms = time.time() * 1000.0
        transport_ms = max(0.0, applied_epoch_ms - packet.t)

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

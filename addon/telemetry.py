"""Capture statistics for telemetry (pure logic, no bpy).

Two clocks, two purposes:
- FPS is a rate: it stays on the monotonic clock (``_applied_times``).
- Transport latency is a difference against a sender-supplied wall-clock
  stamp: ``packet.t`` is epoch ms, so it must be subtracted from the applied
  time on the SAME epoch clock (``time.time()``). Comparing epoch ms against
  monotonic ms always goes negative and clamps to exactly 0.0.
Replay passes the packet's own stamp as the applied epoch time so replayed
packets report zero latency by intent, not because of a clock mismatch.

Session-wide coverage: ``session_max_transport_ms`` and
``session_max_gap_ms`` keep their maxima over EVERY sample, deliberately
outside the rolling 120-sample window, so a stall or latency spike cannot
hide behind the window rolling past it.

Camera-to-rig latency is fail-closed: the only timing source is the optional
``packet.extra["acq_t_ms"]`` stamp from the capture backend. A usable stamp is
an integer (not bool), positive epoch-ms, not later than ``packet.t`` and not
later than the applied epoch ms. Missing stamps keep the camera metric
explicitly unavailable (``None``, never a healthy-looking 0.0); present-but-
unusable stamps are counted as invalid and never enter the aggregates.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from .schema import Packet

STATS_WINDOW = 120  # samples kept for avg/max latency

# UI-facing camera-latency states, derived by ``camera_latency_state``.
CAMERA_STATE_MEASURED = "measured"  # valid samples, no invalid stamps
CAMERA_STATE_MEASURED_INVALID = "measured_invalid"  # valid samples + invalid stamps
CAMERA_STATE_UNAVAILABLE = "unavailable"  # no acquisition stamps seen at all
CAMERA_STATE_INVALID = "invalid"  # stamps present but every one unusable


@dataclass
class CaptureStats:
    """Rolling per-session stats, read by the UI panel each redraw."""

    packets_applied: int = 0
    invalid_packets: int = 0
    packets_dropped_idle: int = 0  # polls that found no new packet
    packets_dropped_stale: int = 0  # queued datagrams replaced by a newer one
    applied_fps: float = 0.0
    avg_transport_ms: float = 0.0
    max_transport_ms: float = 0.0
    session_max_transport_ms: float = 0.0  # max over EVERY sample, not just the window
    session_max_gap_ms: float = 0.0  # max gap between consecutive applied packets, not just the window
    camera_samples: int = 0  # packets with a valid acquisition stamp
    missing_acq_stamps: int = 0  # applied packets without the stamp KEY
    invalid_acq_stamps: int = 0  # present-but-unusable acquisition stamps
    avg_camera_ms: float | None = None  # None until the first valid sample
    max_camera_ms: float | None = None  # rolling, None until the first valid sample
    session_max_camera_ms: float | None = None  # over EVERY valid sample, not just the window
    engine: str = ""
    _latency_window: deque = field(default_factory=lambda: deque(maxlen=STATS_WINDOW), repr=False)
    _applied_times: deque = field(default_factory=lambda: deque(maxlen=STATS_WINDOW), repr=False)
    _camera_window: deque = field(default_factory=lambda: deque(maxlen=STATS_WINDOW), repr=False)

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
        if transport_ms > self.session_max_transport_ms:
            self.session_max_transport_ms = transport_ms

        # Session-wide gap between consecutive applied packets, computed from
        # the previous sample BEFORE the deque append, so the window's maxlen
        # can never affect it (same coverage as session_max_transport_ms).
        if self._applied_times:
            gap_ms = applied_monotonic_ms - self._applied_times[-1]
            if gap_ms > self.session_max_gap_ms:
                self.session_max_gap_ms = gap_ms

        self.packets_applied += 1
        self.engine = packet.engine
        self._record_camera_latency(packet, applied_epoch_ms)
        self._latency_window.append(transport_ms)
        self._applied_times.append(applied_monotonic_ms)
        self._recompute()

    def _record_camera_latency(self, packet: Packet, applied_epoch_ms: float) -> None:
        """Fail-closed camera-to-rig latency from ``extra["acq_t_ms"]``.

        Only KEY ABSENCE is "missing": it increments ``missing_acq_stamps``
        and leaves the camera metric untouched (unavailable, not invalid).
        A present stamp that fails the integer/positivity/chronology checks
        counts as invalid and never aggregates. Neither class invalidates the
        packet itself: transport telemetry and ``packets_applied`` are
        unaffected.
        """
        if "acq_t_ms" not in packet.extra:
            self.missing_acq_stamps += 1
            return
        raw = packet.extra["acq_t_ms"]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            self.invalid_acq_stamps += 1
            return
        if raw > packet.t or raw > applied_epoch_ms:
            self.invalid_acq_stamps += 1
            return
        camera_ms = applied_epoch_ms - raw
        if self.session_max_camera_ms is None or camera_ms > self.session_max_camera_ms:
            self.session_max_camera_ms = camera_ms
        self.camera_samples += 1
        self._camera_window.append(camera_ms)
        if self._camera_window:
            self.avg_camera_ms = sum(self._camera_window) / len(self._camera_window)
            self.max_camera_ms = max(self._camera_window)

    def record_invalid(self, count: int = 1) -> None:
        self.invalid_packets += count

    def record_stale_dropped(self, count: int = 1) -> None:
        self.packets_dropped_stale += count

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
        self.packets_dropped_stale = 0
        self.applied_fps = 0.0
        self.avg_transport_ms = 0.0
        self.max_transport_ms = 0.0
        self.session_max_transport_ms = 0.0
        self.session_max_gap_ms = 0.0
        self.camera_samples = 0
        self.missing_acq_stamps = 0
        self.invalid_acq_stamps = 0
        self.avg_camera_ms = None
        self.max_camera_ms = None
        self.session_max_camera_ms = None
        self.engine = ""
        self._latency_window.clear()
        self._applied_times.clear()
        self._camera_window.clear()


def camera_latency_state(stats: CaptureStats) -> tuple[str, str]:
    """Derive the Blender panel's camera-to-rig line, dependency-free.

    Returns ``(state, text)`` with one of four truthful states:
    - ``CAMERA_STATE_MEASURED``: valid samples, no invalid stamps; reports the
      measured values plus the missing-stamp count when stamps were absent.
    - ``CAMERA_STATE_MEASURED_INVALID``: valid samples kept AND invalid stamps
      present; the panel renders this with an error icon.
    - ``CAMERA_STATE_UNAVAILABLE``: no valid samples and no invalid stamps;
      names the missing-stamp count, or says "no samples yet" when fresh. It
      never shows a measured latency value.
    - ``CAMERA_STATE_INVALID``: stamps present but every one unusable.
    """
    if stats.camera_samples > 0:
        assert stats.avg_camera_ms is not None
        assert stats.max_camera_ms is not None
        assert stats.session_max_camera_ms is not None
        text = (
            f"Camera->Rig: avg {stats.avg_camera_ms:.1f} ms / "
            f"max {stats.max_camera_ms:.1f} ms "
            f"(session max {stats.session_max_camera_ms:.1f} ms)"
        )
        notes = []
        if stats.invalid_acq_stamps:
            notes.append(f"invalid stamps: {stats.invalid_acq_stamps}")
        if stats.missing_acq_stamps:
            notes.append(f"missing stamps: {stats.missing_acq_stamps}")
        if notes:
            text += " - " + ", ".join(notes)
        state = (
            CAMERA_STATE_MEASURED_INVALID
            if stats.invalid_acq_stamps
            else CAMERA_STATE_MEASURED
        )
        return state, text
    if stats.invalid_acq_stamps > 0:
        return (
            CAMERA_STATE_INVALID,
            f"Camera->Rig: unavailable ({stats.invalid_acq_stamps} invalid acquisition stamps)",
        )
    if stats.missing_acq_stamps > 0:
        return (
            CAMERA_STATE_UNAVAILABLE,
            f"Camera->Rig: unavailable (no acquisition stamps in {stats.missing_acq_stamps} packets)",
        )
    return CAMERA_STATE_UNAVAILABLE, "Camera->Rig: unavailable (no samples yet)"

"""Main-thread consumer: timer loop that applies packets to the controller.

Blender threading rules (see TDD section 6):
- This module only ever touches bpy from bpy.app.timers callbacks (main thread).
- Values are written as custom properties on ONE controller object; users bind
  shape keys / bones to them with native drivers (no Python driver expressions).
- Epsilon gating skips depsgraph churn when values barely changed.

Supports two modes through the same application path:
- live: packets come from the UDP receiver
- replay: packets come from a recorded session file, applied with the
  original inter-arrival timing (see session.py)
"""

from __future__ import annotations

import time

import bpy

from .receiver import UdpReceiver
from .session import ReplayScheduler, SessionError, SessionRecorder, read_session
from .telemetry import CaptureStats

POLL_INTERVAL_S = 1.0 / 60.0

SHAPE_PREFIX = "rc_shape_"
POSE_PREFIX = "rc_pose_"
META_PREFIX = "rc_meta_"


class CaptureConsumer:
    """Owns the receiver (or replay scheduler) and the bpy.app.timers tick."""

    def __init__(self, get_controller, epsilon: float = 0.002) -> None:
        """``get_controller`` is a callable returning the target bpy Object or None."""
        self._get_controller = get_controller
        self._epsilon = epsilon
        self._receiver: UdpReceiver | None = None
        self._replay: ReplayScheduler | None = None
        self.recorder: SessionRecorder | None = None
        self._timer_registered = False
        self.stats = CaptureStats()
        self._last_values: dict[str, float] = {}
        # Last seen values of the receiver's cumulative counters, so deltas
        # feed the stats without double counting across ticks.
        self._last_invalid_seen = 0
        self._last_stale_seen = 0
        # Optional FacePointRig (set by the rig-connector bind operator).
        self.face_points = None

    # -- lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._timer_registered

    @property
    def replaying(self) -> bool:
        return self._replay is not None

    def start(self, port: int) -> None:
        if self._timer_registered:
            raise RuntimeError("consumer already running")
        self._receiver = UdpReceiver(port=port)
        self._begin()

    def start_replay(self, session_path: str) -> int:
        """Start replaying a recorded session. Returns the number of skipped lines."""
        if self._timer_registered:
            raise RuntimeError("consumer already running")
        try:
            entries, skipped = read_session(session_path)
        except (OSError, SessionError) as exc:
            raise SessionError(f"cannot load session: {exc}") from exc
        self._replay = ReplayScheduler(entries)
        self._begin()
        return skipped

    def _begin(self) -> None:
        self._last_values.clear()
        self.stats.reset()
        self._last_invalid_seen = 0
        self._last_stale_seen = 0
        if self._receiver is not None:
            self._receiver.reset_counters()
        bpy.app.timers.register(self._tick, first_interval=0.0)
        self._timer_registered = True

    def stop(self) -> None:
        if self._timer_registered and bpy.app.timers.is_registered(self._tick):
            bpy.app.timers.unregister(self._tick)
        self._timer_registered = False
        self._replay = None
        if self._receiver is not None:
            self._receiver.close()
            self._receiver = None
        if self.recorder is not None and self.recorder.is_recording:
            self.recorder.stop()

    # -- timer tick (main thread) ---------------------------------------------

    def _tick(self) -> float | None:
        if not self._timer_registered:
            return None  # stop the timer

        if self._replay is not None:
            now_ms = time.monotonic() * 1000.0
            for packet in self._replay.poll(now_ms):
                self._apply(packet)
            if self._replay.exhausted:
                self._timer_registered = False
                self._replay = None
                return None  # replay finished: stop the timer
            return POLL_INTERVAL_S

        if self._receiver is None:
            return None
        packet = self._receiver.poll_latest()
        if packet is None:
            self.stats.record_idle_poll()
        else:
            self._apply(packet)
        # Feed the receiver's cumulative counters into the stats as deltas so
        # nothing is double counted across ticks.
        invalid_total = self._receiver.invalid_count
        if invalid_total > self._last_invalid_seen:
            self.stats.record_invalid(invalid_total - self._last_invalid_seen)
        self._last_invalid_seen = invalid_total
        stale_total = self._receiver.stale_dropped
        if stale_total > self._last_stale_seen:
            self.stats.record_stale_dropped(stale_total - self._last_stale_seen)
        self._last_stale_seen = stale_total
        return POLL_INTERVAL_S

    # -- application to the controller ----------------------------------------

    def _apply(self, packet) -> None:  # noqa: ANN001 - schema.Packet
        obj = self._get_controller()
        if obj is None:
            self.stats.record_idle_poll()
            return

        now_ms = time.monotonic() * 1000.0

        for name, value in packet.shapes.items():
            self._set_value(obj, SHAPE_PREFIX + name, value)
        for key, value in packet.pose.items():
            self._set_value(obj, POSE_PREFIX + key, value)
        self._set_value(obj, META_PREFIX + "conf", packet.conf, bypass_epsilon=True)

        # Metadata as strings (idempotent: only written when different).
        if obj.get(META_PREFIX + "engine") != packet.engine:
            obj[META_PREFIX + "engine"] = packet.engine

        if self.recorder is not None and self.recorder.is_recording:
            self.recorder.record(packet, int(time.time() * 1000.0))

        if self.face_points is not None:
            self.face_points.apply(packet)

        if self._replay is not None:
            # Replayed packets carry the original send time; latency against
            # the packet's own epoch stamp is zero BY INTENT (replay latency
            # is not meaningful), not because of a clock mismatch.
            self.stats.record_applied(packet, now_ms, float(packet.t))
        else:
            self.stats.record_applied(packet, now_ms, time.time() * 1000.0)

    def _set_value(self, obj: bpy.types.Object, prop: str, value: float, bypass_epsilon: bool = False) -> bool:
        last = self._last_values.get(prop)
        if (
            not bypass_epsilon
            and last is not None
            and abs(value - last) < self._epsilon
            and prop in obj.keys()
        ):
            return False  # below epsilon: skip the write, avoid depsgraph churn
        obj[prop] = value
        self._last_values[prop] = value
        return True

"""Main-thread consumer: timer loop that applies packets to the controller.

Blender threading rules (see TDD section 6):
- This module only ever touches bpy from bpy.app.timers callbacks (main thread).
- Values are written as custom properties on ONE controller object; users bind
  shape keys / bones to them with native drivers (no Python driver expressions).
- Epsilon gating skips depsgraph churn when values barely changed.
"""

from __future__ import annotations

import time

import bpy

from .receiver import UdpReceiver
from .telemetry import CaptureStats

POLL_INTERVAL_S = 1.0 / 60.0

SHAPE_PREFIX = "rc_shape_"
POSE_PREFIX = "rc_pose_"
META_PREFIX = "rc_meta_"


class CaptureConsumer:
    """Owns the receiver and the bpy.app.timers tick while capture is running."""

    def __init__(self, get_controller, epsilon: float = 0.002) -> None:
        """``get_controller`` is a callable returning the target bpy Object or None."""
        self._get_controller = get_controller
        self._epsilon = epsilon
        self._receiver: UdpReceiver | None = None
        self._timer_registered = False
        self.stats = CaptureStats()
        self._last_values: dict[str, float] = {}

    # -- lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._timer_registered

    def start(self, port: int) -> None:
        if self._timer_registered:
            raise RuntimeError("consumer already running")
        self._receiver = UdpReceiver(port=port)
        self._last_values.clear()
        self.stats.reset()
        bpy.app.timers.register(self._tick, first_interval=0.0)
        self._timer_registered = True

    def stop(self) -> None:
        if self._timer_registered and bpy.app.timers.is_registered(self._tick):
            bpy.app.timers.unregister(self._tick)
        self._timer_registered = False
        if self._receiver is not None:
            self._receiver.close()
            self._receiver = None

    # -- timer tick (main thread) ---------------------------------------------

    def _tick(self) -> float:
        if not self._timer_registered or self._receiver is None:
            return None  # stop the timer

        packet = self._receiver.poll_latest()
        if packet is None:
            self.stats.record_idle_poll()
        else:
            self._apply(packet)

        return POLL_INTERVAL_S

    # -- application to the controller ----------------------------------------

    def _apply(self, packet) -> None:  # noqa: ANN001 - schema.Packet
        obj = self._get_controller()
        if obj is None:
            self.stats.record_idle_poll()
            return

        now_ms = time.monotonic() * 1000.0
        changed = False

        for name, value in packet.shapes.items():
            changed |= self._set_value(obj, SHAPE_PREFIX + name, value)
        for key, value in packet.pose.items():
            changed |= self._set_value(obj, POSE_PREFIX + key, value)
        changed |= self._set_value(obj, META_PREFIX + "conf", packet.conf, bypass_epsilon=True)

        # Metadata as strings (idempotent: only written when different).
        if obj.get(META_PREFIX + "engine") != packet.engine:
            obj[META_PREFIX + "engine"] = packet.engine
            changed = True

        self.stats.record_applied(packet, now_ms)
        # `changed` only gates stats verbosity today; props are idempotent writes.

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

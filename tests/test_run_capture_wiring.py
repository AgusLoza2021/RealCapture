"""The parent-owned glue that feeds the dashboard's status lights.

W3 built the heartbeat tracker, W4 built the truth table, and neither owns
``run_capture.py``. These two adapters join them, so they are pinned here:
glue is the part no writer's tests cover, and it is where a late-binding bug
would silently freeze a light at whatever it read on the first call.
"""

import json
import time

from backend.dashboard.hub import DashboardHub
from backend.run_capture import _HeartbeatSource, _tap_camera_age

# Verbatim payload received over UDP from the addon on the reference MPFB2
# character, read with a listener socket bound to the sender's own port:
# the refused point/bone attempt and the bind actually in effect are two
# different numbers, and keeping them apart is the whole point of the field
# split.
REAL_WIRE_BIND = json.loads(
    '{"mode":"shape_keys","channels":52,"head_bone":null,'
    '"rest_displacement_m":2.4393007725113045e-07,'
    '"refused_rest_displacement_m":0.8318656335786587,"skip_reason":"rest_gate"}'
)


class _Tracker:
    """Stands in for ``backend.dashboard.heartbeat.HeartbeatTracker``."""

    def __init__(self, age_s, bind):
        self._age_s = age_s
        self._bind = bind

    def age_s(self, now):  # noqa: ANN001, ANN201 - now is unused by the stub
        return self._age_s

    def bind_report(self):
        return self._bind


class _Backend:
    """A backend that may or may not have been started yet."""


class _StubTap:
    def __init__(self):
        self.slot = None

    def publish(self, frame, t):  # noqa: ANN001 - test stub
        self.slot = (frame, t)

    def peek(self):
        return self.slot


def _lights(**kw):  # noqa: ANN003 - forwarded to the hub
    hub = DashboardHub(**kw)
    return {row["id"]: row for row in hub.snapshot()["connections"]}


def test_heartbeat_source_reports_absence_before_the_backend_starts():
    source = _HeartbeatSource(_Backend())

    assert source.age_s(100.0) is None
    assert source.bind_report() is None


def test_heartbeat_source_re_reads_the_tracker_instead_of_snapshotting_it():
    backend = _Backend()
    source = _HeartbeatSource(backend)

    backend.heartbeat = _Tracker(0.5, REAL_WIRE_BIND)
    assert source.age_s(100.0) == 0.5
    assert source.bind_report() == REAL_WIRE_BIND

    # A restart replaces the tracker; the adapter must follow it, not the
    # instance it happened to see first.
    backend.heartbeat = _Tracker(1.5, {"mode": "none", "channels": 0})
    assert source.age_s(100.0) == 1.5
    assert source.bind_report() == {"mode": "none", "channels": 0}

    backend.heartbeat = None
    assert source.age_s(100.0) is None


def test_camera_age_is_unknown_before_the_first_frame():
    assert _tap_camera_age(_StubTap())() is None


def test_camera_age_is_positive_after_a_frame():
    tap = _StubTap()
    tap.publish("frame", 1.0)

    age = _tap_camera_age(tap)()

    assert age is not None
    assert age > 0.0


def test_the_real_wire_bind_turns_the_blender_light_green_with_the_refusal_reason():
    lights = _lights(blender_source=_HeartbeatSource(_started_backend()))

    assert lights["blender"]["state"] == "green"
    # A green light may still carry the most useful line on the page.
    assert "refused" in lights["blender"]["reason"]
    assert "0.83" in lights["blender"]["reason"]


def test_a_refused_bone_path_never_colours_a_light_by_itself():
    lights = _lights(blender_source=_HeartbeatSource(_started_backend()))

    assert lights["blender"]["detail"]["rest_displacement_m"] < 0.25
    assert lights["blender"]["detail"]["refused_rest_displacement_m"] > 0.25


def test_silence_is_never_green():
    silent = _Backend()
    silent.heartbeat = _Tracker(9.0, REAL_WIRE_BIND)
    never = _Backend()

    assert _lights(blender_source=_HeartbeatSource(silent))["blender"]["state"] == "red"
    assert _lights(blender_source=_HeartbeatSource(never))["blender"]["state"] == "red"
    assert _lights()["blender"]["state"] == "red"
    assert _lights()["camera"]["state"] == "red"


def test_a_working_rig_drives_a_green_camera_light_from_the_tap():
    tap = _StubTap()
    tap.publish("frame", time.monotonic())

    lights = _lights(camera_age_s=_tap_camera_age(tap))

    assert lights["camera"]["state"] == "green"


def _started_backend():
    backend = _Backend()
    backend.heartbeat = _Tracker(0.5, REAL_WIRE_BIND)
    return backend

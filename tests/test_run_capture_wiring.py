"""The parent-owned glue that feeds the dashboard's status lights.

W3 built the heartbeat tracker, W4 built the truth table, and neither owns
``run_capture.py``. These two adapters join them, so they are pinned here:
glue is the part no writer's tests cover, and it is where a late-binding bug
would silently freeze a light at whatever it read on the first call.
"""

import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from backend.dashboard.hub import DashboardHub
from backend.dashboard.server import websocket_implementation
from backend.run_capture import _HeartbeatSource, _start_dashboard, _tap_camera_age

REPO_ROOT = Path(__file__).resolve().parents[1]

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


class _StubCaptureBackend:
    """The whole surface ``_start_dashboard`` touches on a real backend."""

    def __init__(self):
        self.on_frame = None
        self.on_packet = None
        self.on_send_error = None
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


def _free_port():
    """A port nothing is listening on, released before the caller binds it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _dashboard_args(port):
    return SimpleNamespace(
        stream_fps=12.0,
        dashboard=port,
        engine="mediapipe",
        host="127.0.0.1",
        port=11111,
    )


def _await_http(url, deadline_s=15.0):
    """Poll a real socket until it answers, so a bind race is not a failure."""
    deadline = time.monotonic() + deadline_s
    last_exc = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                return response.status, response.read(), response.headers.get("content-type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("content-type", "")
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
            time.sleep(0.05)
    raise AssertionError(f"{url} never answered within {deadline_s}s: {last_exc!r}")


def test_the_entry_points_dashboard_path_actually_serves_the_window():
    """Run the branch every other test here skips.

    Everything above reaches the server through ``TestClient``, so all of it
    stayed green while ``_start_dashboard`` raised ``NameError: name
    'threading' is not defined`` on its last line and killed ``main()``
    before the window could ever be served. A suite that never executes the
    branch it is judging reports success it has not earned, so this test
    starts the real server on a real port.

    The uvicorn server object is local to ``_start_dashboard`` and cannot be
    reached to shut it down; the daemon thread dies with the test process,
    which is why this runs once rather than per-case.
    """
    port = _free_port()
    backend = _StubCaptureBackend()

    thread, hub = _start_dashboard(backend, _dashboard_args(port))

    assert thread.daemon is True
    assert hub is not None
    assert backend.on_frame is not None, "the camera preview was never wired"
    assert backend.on_packet is not None, "the status lights were never wired"

    status, body, content_type = _await_http(f"http://127.0.0.1:{port}/")
    assert status == 200
    assert "text/html" in content_type
    assert b"<html" in body.lower()

    status, body, _ = _await_http(f"http://127.0.0.1:{port}/api/status")
    assert status == 200
    lights = {row["id"]: row for row in json.loads(body)["connections"]}
    assert set(lights) == {"camera", "packets", "blender"}
    # The stub backend never emits a frame, so the honest answer is red with
    # a reason - never a quiet green.
    assert lights["camera"]["state"] == "red"
    assert lights["camera"]["reason"].strip()

    # Same honesty rule on the snapshot endpoint: no fabricated frame.
    status, body, content_type = _await_http(f"http://127.0.0.1:{port}/camera.jpg")
    assert status == 503
    assert "text/plain" in content_type
    assert body.strip(), "503 carried no reason"


class TestTheDashboardCanActuallyPush:
    """The WebSocket dependency the suite can never notice by testing.

    ``TestClient`` answers WebSocket connections in-process, so every
    dashboard test stayed green while uvicorn refused every upgrade request
    in production with "No supported WebSocket library detected". The page
    then fell back to 1 s polling and kept reporting live numbers, so the
    degradation was invisible from inside the app too. Only a browser - or
    the dependency list - can see this.
    """

    def test_requirements_name_a_websocket_implementation(self) -> None:
        declared = set()
        for line in (REPO_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for sep in (">=", "==", "~=", ">"):
                if sep in line:
                    line = line.split(sep, 1)[0]
                    break
            declared.add(line.strip().lower())
        assert declared & {"websockets", "wsproto", "uvicorn[standard]"}, (
            f"no WebSocket implementation is declared, so uvicorn will refuse "
            f"/ws and the page can only poll; declared: {sorted(declared)}"
        )

    def test_absence_is_reported_rather_than_assumed(self) -> None:
        assert websocket_implementation(find_spec=lambda name: None) is None

    def test_the_installed_name_is_returned(self) -> None:
        def fake(name):
            return object() if name == "wsproto" else None

        assert websocket_implementation(find_spec=fake) == "wsproto"

    def test_a_finder_that_raises_is_not_a_crash(self) -> None:
        def fake(name):
            raise ModuleNotFoundError(name)

        assert websocket_implementation(find_spec=fake) is None

    def test_the_real_environment_is_asked_and_named(self) -> None:
        found = websocket_implementation()
        assert found is None or found in ("websockets", "wsproto")

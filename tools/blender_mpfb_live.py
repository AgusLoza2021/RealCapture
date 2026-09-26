"""Real-character LIVE demo: the MPFB2 character driven live by camera packets.

The missing third thing between the two other demos:

- tools/blender_live_demo.py  -> live UDP, but a synthetic 323-vertex grid
- tools/blender_mpfb_demo.py  -> the real character, but fed values directly
- THIS file                   -> the real character, bound through the addon,
                                 driven live by UDP packets from the camera

The character is NOT in the repository. Use the generated MPFB2 human in the
isolated Blender config (default path, override with --blend):

    C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/tmp/character.blend

MPFB2 lives in an isolated config: set these BEFORE launching Blender
(the script cannot set them for a running Blender; without them MPFB2 is
not found and the script exits with code 4):

    set BLENDER_USER_CONFIG=C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/env/config
    set BLENDER_USER_EXTENSIONS=C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/env/extensions
    set BLENDER_USER_DATA=C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/env/data

Producer (run in another terminal; do NOT run from this script):

    backend/.venv/Scripts/python.exe backend/run_capture.py --engine mediapipe --camera 0 --fps 30 --port 11111

Modes:

  GUI UDP listen (default; watch the face move in a real Blender window):

      "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
          --factory-startup --python tools/blender_mpfb_live.py -- [--port 11111]

  Headless self-test (no camera, no network; proves the real consumer apply
  path moves a NAMED shape key on the real character):

      ... blender.exe -b --factory-startup --python tools/blender_mpfb_live.py -- \
          --self-test [--channel jawOpen] [--value 0.9]

  Bounded headless live run (the real UDP receive path, pumped manually for
  exactly N seconds because bpy.app.timers do not fire under -b):

      ... blender.exe -b --factory-startup --python tools/blender_mpfb_live.py -- \
          --seconds 10 [--port 11111]

  GUI self-drive (synthetic ramp, no network; useful for a render check):

      ... blender.exe --factory-startup --python tools/blender_mpfb_live.py -- --self-drive

Bind honesty: on this character the bind reports
    "Warning: Bound 52 shape keys (consumer-driven) only: point/bone path
     REJECTED ... reverted to shape keys only"
(the T9 fix: the character's bone named 'head' is at chest height). That
state is CORRECT here and this demo works in it: it drives the 52 shape
keys through CaptureConsumer -> FacePointRig.apply and never depends on the
bone path. The bind result is always printed, including the rejection.

Exit codes (same convention as tools/blender_mpfb_demo.py):
    0  success
    1  assertion failed (self-test found no movement / --seconds saw no packets)
    2  unexpected error
    3  the character .blend does not exist
    4  MPFB2 is not installed in this Blender configuration

Mutation proof: `--self-test --value 0` must exit 1 with a legible
"no vertex moved" message; a self-test that cannot fail is worthless.
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import bpy  # noqa: E402

EXIT_OK = 0
EXIT_ASSERT = 1
EXIT_ERROR = 2
EXIT_NO_BLEND = 3
EXIT_NO_MPFB = 4

DEFAULT_BLEND = "C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/tmp/character.blend"
MPFB_MODULE = "bl_ext.user_default.mpfb"
DEFAULT_PORT = 11111
DEFAULT_CHANNEL = "jawOpen"
DEFAULT_VALUE = 0.9
DEFAULT_SECONDS = 10.0

PUMP_HZ = 30  # manual tick rate for the headless --seconds loop

ENV_HINT = (
    "MPFB2 env vars must be set before launching Blender:\n"
    "  BLENDER_USER_CONFIG=C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/env/config\n"
    "  BLENDER_USER_EXTENSIONS=C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/env/extensions\n"
    "  BLENDER_USER_DATA=C:/Users/Lozita/AppData/Local/Temp/rc_mpfb/env/data"
)

PRODUCER_HINT = (
    "backend/.venv/Scripts/python.exe backend/run_capture.py "
    "--engine mediapipe --camera 0 --fps 30 --port {port}"
)


def _load_tool_module(name: str):
    """Import a tools/ demo module by path (repo layout, never installed)."""
    path = os.path.join(REPO_ROOT, "tools", f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mpfb = _load_tool_module("blender_mpfb_demo")
_live = _load_tool_module("blender_live_demo")


# -- scene setup (real scan -> bind, mpfb_demo conventions) -------------------

def _open_and_bind(blend_path: str):
    """Open the real character, bind through the addon, return (mesh, consumer).

    Prints the bind result honestly: the consumer-driven-only warning when
    the point/bone path was rejected (expected on this character), full-bind
    counts otherwise. Never a bare success line.
    """
    _mpfb._open_blend(blend_path)

    mesh_obj = _mpfb._find_face_mesh()
    armature, head_bone = _mpfb._find_armature()
    if mesh_obj is None or armature is None:
        print(f"MPFB LIVE FAILED: no MPFB face mesh / armature with a head bone "
              f"in {blend_path} (mesh={mesh_obj}, armature={armature})")
        raise SystemExit(EXIT_ERROR)

    import addon  # RealCapture addon, loaded by path, never installed

    addon.register()
    controller = bpy.data.objects.get("RealCapture_Controller")
    if controller is None:
        controller = bpy.data.objects.new("RealCapture_Controller", None)
        bpy.context.scene.collection.objects.link(controller)

    settings = bpy.context.scene.realcapture
    settings.controller = controller
    settings.rig_face_mesh = mesh_obj
    settings.rig_armature = armature
    settings.rig_head_bone = head_bone

    if bpy.ops.realcapture.scan_rig() != {"FINISHED"}:
        print("MPFB LIVE FAILED: scan_rig did not finish")
        raise SystemExit(EXIT_ERROR)
    if bpy.ops.realcapture.bind_rig() != {"FINISHED"}:
        print("MPFB LIVE FAILED: bind_rig did not finish (see operator report above)")
        raise SystemExit(EXIT_ERROR)

    from addon.ui import _get_consumer

    consumer = _get_consumer()
    _print_bind_result(mesh_obj, consumer)
    return mesh_obj, consumer


def _print_bind_result(mesh_obj, consumer) -> None:
    """Mirror the operator's honest bind outcome to stdout (it uses reports)."""
    from addon.wizard import _skip_detail

    face_points = getattr(consumer, "face_points", None)
    report = getattr(face_points, "bind_report", None) if face_points else None
    driven = [k for k in mesh_obj.get("rc_driven_shapekeys", [])]
    if report is not None and getattr(report, "skip_reason", None) in (
            "no_head_bone", "rest_gate"):
        print(f"Warning: Bound {len(driven)} shape keys (consumer-driven) only: "
              f"{_skip_detail(report)}")
        print("This demo works in that state: it drives the shape keys and "
              "does not depend on the bone path.")
    elif face_points is not None:
        points = len(getattr(face_points, "empty_names", []))
        head = getattr(report, "head_bone", None) if report else None
        print(f"Bound: {len(driven)} shape keys (consumer-driven), "
              f"{points} point transforms, head bone {head!r} (point/bone path live)")


# -- live summary -------------------------------------------------------------

def _summary_line(mesh_obj, stats, tag: str) -> str:
    """One human-readable line: is the chain alive, and what is the face doing?"""
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    driven = [name for name in mesh_obj.get("rc_driven_shapekeys", [])
              if name in key_blocks]
    ranked = sorted(
        ((key_blocks[name].value, name) for name in driven),
        key=lambda item: abs(item[0]), reverse=True)
    top = " ".join(f"{name}={value:+.2f}" for value, name in ranked[:5]) or "none"
    return (f"[{tag}] packets={stats.packets_applied} fps={stats.applied_fps:.1f} "
            f"transport={stats.avg_transport_ms:.1f}ms top: {top}")


def _register_gui_summary(mesh_obj, consumer, interval: float = 1.0) -> None:
    """GUI mode: print the live summary once per second via bpy.app.timers."""

    def tick() -> float:
        print(_summary_line(mesh_obj, consumer.stats,
                            time.strftime("%H:%M:%S")))
        return interval

    bpy.app.timers.register(tick, first_interval=interval)


# -- modes ----------------------------------------------------------------------

def mode_udp_listen(port: int, blend_path: str) -> int:
    mesh_obj, consumer = _open_and_bind(blend_path)
    consumer.start(port=port)
    print(f"=== RealCapture MPFB LIVE: UDP-listen mode on port {port} ===")
    print("Producer (run in another terminal):")
    print(f"  {PRODUCER_HINT.format(port=port)}")
    print("Incoming packets drive the real face through the consumer apply "
          "path (bpy.app.timers, non-blocking). Live summary every second; "
          "close the Blender window to stop.")
    _register_gui_summary(mesh_obj, consumer)
    return EXIT_OK


def mode_self_test(channel: str, value: float, blend_path: str) -> int:
    mesh_obj, consumer = _open_and_bind(blend_path)
    face_points = consumer.face_points
    if face_points is None:
        print("MPFB LIVE FAILED: bind produced no FacePointRig; the consumer "
              "apply path cannot drive this character")
        return EXIT_ERROR

    key_blocks = mesh_obj.data.shape_keys.key_blocks
    if channel not in key_blocks:
        print(f"MPFB LIVE FAILED: shape key '{channel}' does not exist on "
              f"{mesh_obj.name} (driven keys: "
              f"{list(mesh_obj.get('rc_driven_shapekeys', []))})")
        return EXIT_ASSERT

    baseline = _mpfb._live_coords(mesh_obj)
    consumer._apply(_live.make_packet({channel: value}))

    target_key = key_blocks[channel]
    vert, delta = _mpfb._max_move(
        mesh_obj, _mpfb._controlled_vertices(target_key), baseline)
    print(f"Driven '{channel}'={value}: shape key value {target_key.value:.4f}, "
          f"strongest controlled vertex #{vert} moved {delta:.4f} Blender units "
          "relative to Basis")

    failures: list[str] = []
    if abs(target_key.value - value) > 1e-4:
        failures.append(f"shape key value did not reach the packet value "
                        f"({target_key.value:.4f} != {value:.4f})")
    if delta <= _live.MOVE_THRESHOLD:
        failures.append(f"no vertex moved relative to Basis on '{channel}' "
                        f"(max delta {delta:.6f} <= {_live.MOVE_THRESHOLD})")
    if failures:
        for failure in failures:
            print(f"FAILED: {failure}")
        print("MPFB LIVE SELF-TEST FAILED")
        return EXIT_ASSERT

    print("MPFB LIVE SELF-TEST PASSED")
    return EXIT_OK


def mode_seconds(seconds: float, port: int, blend_path: str) -> int:
    """Bounded headless run of the REAL UDP receive path.

    bpy.app.timers do not fire under -b, so the consumer's tick is pumped
    manually in a wall-clock-bounded loop. The socket is non-blocking and
    the sleep never overshoots the deadline: this loop always terminates.
    """
    mesh_obj, consumer = _open_and_bind(blend_path)
    consumer.start(port=port)
    print(f"=== RealCapture MPFB LIVE: bounded headless run, {seconds:g}s "
          f"on port {port} ===")
    print(f"Producer: {PRODUCER_HINT.format(port=port)}")

    start = time.monotonic()
    deadline = start + seconds
    next_report = start + 1.0
    while time.monotonic() < deadline:
        consumer._tick()  # real receive path; timers are inert under -b
        now = time.monotonic()
        if now >= next_report:
            elapsed = now - start
            print(_summary_line(mesh_obj, consumer.stats, f"{elapsed:.0f}s"))
            next_report += 1.0
        time.sleep(min(1.0 / PUMP_HZ, max(0.0, deadline - time.monotonic())))

    consumer.stop()
    elapsed = time.monotonic() - start
    print(_summary_line(mesh_obj, consumer.stats, f"final {elapsed:.1f}s"))
    if consumer.stats.packets_applied == 0:
        print("MPFB LIVE FAILED: no packets received")
        return EXIT_ASSERT
    print("MPFB LIVE OK")
    return EXIT_OK


_DRIVE_INTERVAL = 1.0 / 30.0


def mode_self_drive(blend_path: str) -> int:
    """GUI synthetic ramp, no network: useful for a render check."""
    mesh_obj, consumer = _open_and_bind(blend_path)
    driven = [name for name in mesh_obj.get("rc_driven_shapekeys", [])
              if name in mesh_obj.data.shape_keys.key_blocks]

    def drive_tick() -> float:
        t = time.monotonic()
        shapes = {}
        for i, name in enumerate(driven):
            phase = 0.7 * i
            if "blink" in name:
                shapes[name] = max(0.0, math.sin(t * 1.7 + phase) ** 8)
            else:
                shapes[name] = 0.5 + 0.5 * math.sin(t * 0.8 + phase)
        if shapes:
            consumer._apply(_live.make_packet(shapes))
        return _DRIVE_INTERVAL

    bpy.app.timers.register(drive_tick, first_interval=0.5)
    print(f"=== RealCapture MPFB LIVE: self-drive mode on {mesh_obj.name} ===")
    print(f"Autonomously ramping {len(driven)} driven shape keys through the "
          "real consumer apply path. Close the Blender window to stop.")
    return EXIT_OK


# -- entry ------------------------------------------------------------------------

def _parse_args() -> dict:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parsed: dict = {
        "mode": "udp", "port": DEFAULT_PORT, "channel": DEFAULT_CHANNEL,
        "value": DEFAULT_VALUE, "seconds": DEFAULT_SECONDS, "blend": None,
    }
    positional: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--self-test":
            parsed["mode"] = "self_test"
        elif arg == "--self-drive":
            parsed["mode"] = "self_drive"
        elif arg == "--seconds":
            i += 1
            parsed["mode"] = "seconds"
            parsed["seconds"] = float(args[i]) if i < len(args) else DEFAULT_SECONDS
        elif arg == "--port":
            i += 1
            parsed["port"] = int(args[i]) if i < len(args) else DEFAULT_PORT
        elif arg == "--channel":
            i += 1
            parsed["channel"] = args[i] if i < len(args) else DEFAULT_CHANNEL
        elif arg == "--value":
            i += 1
            parsed["value"] = float(args[i]) if i < len(args) else DEFAULT_VALUE
        elif arg == "--blend":
            i += 1
            parsed["blend"] = args[i] if i < len(args) else None
        else:
            positional.append(arg)
        i += 1
    if positional and parsed["blend"] is None:
        parsed["blend"] = positional[0]
    return parsed


def main() -> int:
    args = _parse_args()
    blend_path = args["blend"] or DEFAULT_BLEND

    if not os.path.isfile(blend_path):
        print(f"MPFB LIVE SKIPPED: character .blend not found: {blend_path!r} "
              "(generate it with MPFB2 first, or pass a path after '--')")
        return EXIT_NO_BLEND
    if not _mpfb._mpfb_installed():
        print(f"MPFB LIVE SKIPPED: MPFB2 ({MPFB_MODULE}) is not installed in "
              "this Blender configuration.")
        print(ENV_HINT)
        return EXIT_NO_MPFB

    if args["mode"] == "self_test":
        return mode_self_test(args["channel"], args["value"], blend_path)
    if args["mode"] == "seconds":
        return mode_seconds(args["seconds"], args["port"], blend_path)
    if args["mode"] == "self_drive":
        return mode_self_drive(blend_path)
    return mode_udp_listen(args["port"], blend_path)


if __name__ == "__main__":
    try:
        _code = main()
    except SystemExit as exc:
        _code = exc.code if isinstance(exc.code, int) else EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - unexpected failures get full diagnosis
        import traceback

        traceback.print_exc()
        print(f"MPFB LIVE ERROR: {exc}")
        _code = EXIT_ERROR
    background = "-b" in sys.argv or "--background" in sys.argv
    if background or _code != 0:
        sys.exit(_code)
    # GUI live modes: keep the window open (Blender continues after the script).

"""Real-character LIVE demo: the MPFB2 character driven live by camera packets.

The missing third thing between the two other demos:

- tools/blender_live_demo.py  -> live UDP, but a synthetic 323-vertex grid
- tools/blender_mpfb_demo.py  -> the real character, but fed values directly
- THIS file                   -> the real character, bound through the addon,
                                 driven live by UDP packets from the camera

The character is NOT in the repository. Use the generated MPFB2 human from
your isolated Blender + MPFB2 environment. The path is resolved in this
order (first one that exists wins):

    1. the --blend command-line argument
    2. the RC_CHARACTER environment variable
    3. the RC_MPFB_ROOT default layout: <RC_MPFB_ROOT>\tmp\character.blend
       (RC_MPFB_ROOT itself defaults to %LOCALAPPDATA%\RealCapture\mpfb)

MPFB2 lives in an isolated config: set these BEFORE launching Blender
(the script cannot set them for a running Blender; without them MPFB2 is
not found and the script exits with code 4). The demo launchers derive all
three from RC_MPFB_ROOT automatically:

    set BLENDER_USER_CONFIG=<RC_MPFB_ROOT>\env\config
    set BLENDER_USER_EXTENSIONS=<RC_MPFB_ROOT>\env\extensions
    set BLENDER_USER_DATA=<RC_MPFB_ROOT>\env\data

Producer (run in another terminal; do NOT run from this script):

    backend/.venv/Scripts/python.exe backend/run_capture.py --engine mediapipe --camera 0 --fps 30 --port 11111

Modes:

  GUI UDP listen (default; watch the face move in a real Blender window):

      blender.exe --factory-startup --python tools/blender_mpfb_live.py -- [--port 11111]

  Headless self-test (no camera, no network; proves the real consumer apply
  path moves a NAMED shape key on the real character):

      ... blender.exe -b --factory-startup --python tools/blender_mpfb_live.py -- \
          --self-test [--channel jawOpen] [--value 0.9]

  Bounded headless live run (the real UDP receive path, pumped manually for
  exactly N seconds because bpy.app.timers do not fire under -b):

      ... blender.exe -b --factory-startup --python tools/blender_mpfb_live.py -- \
          --seconds 10 [--port 11111]

  Headless 52-channel sweep (ONE Blender session; measured per-channel vertex
  displacement, OK/DEAD verdict per channel; exit 1 if any channel is DEAD):

      ... blender.exe -b --factory-startup --python tools/blender_mpfb_live.py -- \
          --sweep [--value 1.0]

  Headless named-expression pose renders to soak_output/mpfb_pose_<name>.png
  (repeatable; --pose all renders every pose):

      ... blender.exe -b --factory-startup --python tools/blender_mpfb_live.py -- \
          --pose blink --pose smile ...

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

import hashlib
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

MPFB_MODULE = "bl_ext.user_default.mpfb"
DEFAULT_PORT = 11111
DEFAULT_CHANNEL = "jawOpen"
DEFAULT_VALUE = 0.9
DEFAULT_SECONDS = 10.0

# -- sweep / pose constants -----------------------------------------------------

# Drive value used by --sweep unless --value is given explicitly.
SWEEP_DRIVE_VALUE = 1.0
# Max vertex displacement (metres, evaluated mesh vs rest) at or below which a
# channel is declared DEAD. 1 mm: an ARKit control that only moves the mesh by
# less than this does not visibly act on this character.
SWEEP_DEAD_THRESHOLD = 0.001

# Named expression poses: channel name -> value. Reset to all-zero first.
POSES: dict[str, dict[str, float]] = {
    "blink": {
        "eyeBlinkLeft": 1.0,
        "eyeBlinkRight": 1.0,
    },
    "wink": {
        "eyeBlinkLeft": 1.0,
    },
    "smile": {
        "mouthSmileLeft": 0.9,
        "mouthSmileRight": 0.9,
        "cheekSquintLeft": 0.5,
        "cheekSquintRight": 0.5,
        "mouthDimpleLeft": 0.4,
        "mouthDimpleRight": 0.4,
    },
    "angry": {
        # Anger is brow-down + narrow eyes + a pressed, down-turned mouth.
        # NOTE: browInnerUp is deliberately ABSENT here. It is the sadness
        # cue (inner brow raised, the "puppy eyes" shape) and it actively
        # fights anger: the first version of this pose included it at 0.3 and
        # the render came out looking merely annoyed.
        "browDownLeft": 1.0,
        "browDownRight": 1.0,
        "eyeSquintLeft": 0.85,
        "eyeSquintRight": 0.85,
        "cheekSquintLeft": 0.4,
        "cheekSquintRight": 0.4,
        "noseSneerLeft": 0.85,
        "noseSneerRight": 0.85,
        "mouthUpperUpLeft": 0.6,
        "mouthUpperUpRight": 0.6,
        "mouthPressLeft": 0.6,
        "mouthPressRight": 0.6,
        "mouthFrownLeft": 1.0,
        "mouthFrownRight": 1.0,
    },
    "surprise": {
        "browInnerUp": 1.0,
        "browOuterUpLeft": 1.0,
        "browOuterUpRight": 1.0,
        "eyeWideLeft": 1.0,
        "eyeWideRight": 1.0,
        "jawOpen": 0.9,
    },
}
POSE_ORDER = ("blink", "wink", "smile", "angry", "surprise")
POSE_OUTPUT_DIR = os.path.join(REPO_ROOT, "soak_output")

PUMP_HZ = 30  # manual tick rate for the headless --seconds loop

ENV_HINT = (
    "MPFB2 env vars must be set before launching Blender (the demo launchers "
    "derive them from RC_MPFB_ROOT):\n"
    "  BLENDER_USER_CONFIG=<RC_MPFB_ROOT>\\env\\config\n"
    "  BLENDER_USER_EXTENSIONS=<RC_MPFB_ROOT>\\env\\extensions\n"
    "  BLENDER_USER_DATA=<RC_MPFB_ROOT>\\env\\data"
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


# -- sweep / pose helpers -------------------------------------------------------

def _reset_all_shape_values(mesh_obj) -> None:
    """Set EVERY shape key value to 0 and force a depsgraph update.

    Robust on purpose: the value is never trusted from a write alone. After the
    update the values are read back; a key that refuses to go to 0 is reported
    (twice) instead of silently leaking into the next measurement.
    """
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    for _attempt in range(2):
        for key in key_blocks:
            key.value = 0.0
        bpy.context.view_layer.update()
        stuck = [key.name for key in key_blocks if abs(key.value) > 1e-9]
        if not stuck:
            return
        print(f"Warning: shape keys did not reset to 0 after update: {stuck}; "
              "retrying once")
    print("MPFB LIVE WARNING: some shape key values are still non-zero after "
          "reset; subsequent measurements may be contaminated")


def _max_vertex_displacement(mesh_obj, rest_coords: list) -> float:
    """Max |live - rest| over ALL evaluated mesh vertices, in metres."""
    live = _mpfb._live_coords(mesh_obj)
    return max((a - b).length for a, b in zip(live, rest_coords))


def _setup_render(mesh_obj) -> None:
    """Camera/lighting/render setup, same framing as the ad-hoc render script
    that produced the proven soak_output/mpfb_face_*.png set:
    Cycles 64 samples denoised, 900x900, sun key+fill, track-to camera on the
    geometric head centre. A human can therefore compare pose renders against
    the existing face renders directly.
    """
    import mathutils

    V = mathutils.Vector
    for name in ("Cube", "Light", "Camera"):
        obj = bpy.data.objects.get(name)
        if obj:
            obj.hide_render = True
            obj.hide_viewport = True

    wg = [mesh_obj.matrix_world @ v.co for v in mesh_obj.data.vertices]
    top = max(p.z for p in wg)
    head_pts = [p for p in wg if p.z > top - 0.30]
    hc = sum(head_pts, V((0, 0, 0))) / len(head_pts)

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 900
    scene.render.image_settings.file_format = "PNG"
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = \
        (0.28, 0.32, 0.38, 1.0)
    for name, rot, energy in (("SunKey", (1.05, 0.0, 0.45), 5.0),
                              ("SunFill", (1.35, 0.0, -1.0), 2.2)):
        light_data = bpy.data.lights.new(name, "SUN")
        light_data.energy = energy
        light_obj = bpy.data.objects.new(name, light_data)
        light_obj.rotation_euler = rot
        scene.collection.objects.link(light_obj)
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    target = bpy.data.objects.new("Aim", None)
    scene.collection.objects.link(target)
    target.location = hc
    cam.constraints.new("TRACK_TO").target = target
    cam.location = hc + V((0.06, -0.52, 0.045))
    cam_data.clip_start = 0.01
    cam_data.clip_end = 20


def mode_sweep(value: float, blend_path: str) -> int:
    """Drive EVERY ARKit channel to `value` (one packet each, real consumer
    apply path) and measure the max vertex displacement of the evaluated mesh
    against the all-zero rest state. One Blender session for all 52 channels.
    """
    from addon.rigprofile.channels import ARKIT_CHANNELS

    mesh_obj, consumer = _open_and_bind(blend_path)
    if consumer.face_points is None:
        print("MPFB LIVE FAILED: bind produced no FacePointRig; the consumer "
              "apply path cannot drive this character")
        return EXIT_ERROR

    key_blocks = mesh_obj.data.shape_keys.key_blocks
    _reset_all_shape_values(mesh_obj)
    rest_coords = _mpfb._live_coords(mesh_obj)
    print(f"SWEEP: driving {len(ARKIT_CHANNELS)} channels to {value:g} each, "
          f"DEAD threshold {SWEEP_DEAD_THRESHOLD:g} m "
          f"({len(rest_coords)} mesh vertices per measurement)")

    results: list[tuple[str, float, str, float]] = []  # name, disp, verdict, readback
    for channel in ARKIT_CHANNELS:
        if channel not in key_blocks:
            results.append((channel, 0.0, "DEAD", float("nan")))
            print(f"Warning: channel '{channel}' has no shape key on "
                  f"{mesh_obj.name}; measured as DEAD")
            continue
        consumer._apply(_live.make_packet({channel: value}))
        bpy.context.view_layer.update()
        disp = _max_vertex_displacement(mesh_obj, rest_coords)
        readback = key_blocks[channel].value
        verdict = "OK" if disp > SWEEP_DEAD_THRESHOLD else "DEAD"
        results.append((channel, disp, verdict, readback))
        _reset_all_shape_values(mesh_obj)

    print(f"\n{'channel':<22} {'max disp (m)':>12}  verdict")
    for channel, disp, verdict, _readback in results:
        print(f"{channel:<22} {disp:12.6f}  {verdict}")

    dead = [name for name, _d, verdict, _r in results if verdict == "DEAD"]
    n_ok = len(results) - len(dead)
    print(f"\nSWEEP: {n_ok}/{len(results)} channels moved geometry")
    if dead:
        for channel in dead:
            disp = next(d for n, d, v, _r in results if n == channel and v == "DEAD")
            print(f"DEAD: {channel} (max displacement {disp:.6f} m)")
        print("MPFB LIVE SWEEP FAILED")
        return EXIT_ASSERT
    print("MPFB LIVE SWEEP PASSED")
    return EXIT_OK


def mode_pose(names: list[str], blend_path: str) -> int:
    """Render named expression poses (reset -> apply via the real consumer
    path -> render) to soak_output/mpfb_pose_<name>.png. Never touches the
    existing soak_output/mpfb_face_*.png files (different prefix).
    """
    expanded: list[str] = []
    for name in names:
        if name == "all":
            expanded.extend(POSE_ORDER)
        else:
            expanded.append(name)
    unknown = [name for name in expanded if name not in POSES]
    if unknown:
        print(f"MPFB LIVE FAILED: unknown pose name(s) {unknown}; "
              f"known poses: {list(POSE_ORDER)} (or 'all')")
        return EXIT_ERROR

    mesh_obj, consumer = _open_and_bind(blend_path)
    if consumer.face_points is None:
        print("MPFB LIVE FAILED: bind produced no FacePointRig; the consumer "
              "apply path cannot drive this character")
        return EXIT_ERROR

    _setup_render(mesh_obj)
    os.makedirs(POSE_OUTPUT_DIR, exist_ok=True)
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    for name in expanded:
        shapes = POSES[name]
        _reset_all_shape_values(mesh_obj)
        consumer._apply(_live.make_packet(shapes))
        bpy.context.view_layer.update()
        got = {ch: round(key_blocks[ch].value, 3)
               for ch in shapes if ch in key_blocks}
        path = os.path.join(POSE_OUTPUT_DIR, f"mpfb_pose_{name}.png")
        if os.path.basename(path).startswith("mpfb_face_"):
            print(f"MPFB LIVE FAILED: refusing to overwrite existing "
                  f"soak_output/mpfb_face_*.png renders")
            return EXIT_ERROR
        bpy.context.scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        if not os.path.isfile(path):
            print(f"MPFB LIVE FAILED: render did not write {path}")
            return EXIT_ERROR
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        print(f"WROTE: {path}  {size} bytes  sha256={digest}")
        print(f"  pose '{name}' keys read back from the real mesh = {got}")
    print(f"MPFB LIVE POSE OK: rendered {len(expanded)} pose(s)")
    return EXIT_OK


# -- entry ------------------------------------------------------------------------

def _parse_args() -> dict:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parsed: dict = {
        "mode": "udp", "port": DEFAULT_PORT, "channel": DEFAULT_CHANNEL,
        "value": DEFAULT_VALUE, "seconds": DEFAULT_SECONDS, "blend": None,
        "poses": [], "value_given": False,
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
        elif arg == "--sweep":
            parsed["mode"] = "sweep"
        elif arg == "--pose":
            i += 1
            if i < len(args):
                parsed["poses"].append(args[i])
        elif arg == "--port":
            i += 1
            parsed["port"] = int(args[i]) if i < len(args) else DEFAULT_PORT
        elif arg == "--channel":
            i += 1
            parsed["channel"] = args[i] if i < len(args) else DEFAULT_CHANNEL
        elif arg == "--value":
            i += 1
            parsed["value"] = float(args[i]) if i < len(args) else DEFAULT_VALUE
            parsed["value_given"] = True
        elif arg == "--blend":
            i += 1
            parsed["blend"] = args[i] if i < len(args) else None
        else:
            positional.append(arg)
        i += 1
    if positional and parsed["blend"] is None:
        parsed["blend"] = positional[0]
    return parsed


def _resolve_blend_path(explicit: str | None) -> str | None:
    """Character .blend resolution order: --blend, RC_CHARACTER, RC_MPFB_ROOT.

    Returns the first candidate that exists on disk, or None when none can be
    resolved; the caller must then name all three ways to set the path and
    exit with EXIT_NO_BLEND - never silently fall back to something else.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    rc_character = os.environ.get("RC_CHARACTER")
    if rc_character:
        candidates.append(rc_character)
    rc_root = os.environ.get("RC_MPFB_ROOT") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "RealCapture", "mpfb")
    if rc_root:
        candidates.append(os.path.join(rc_root, "tmp", "character.blend"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def main() -> int:
    args = _parse_args()
    blend_path = _resolve_blend_path(args["blend"])

    if blend_path is None:
        print("MPFB LIVE SKIPPED: no character .blend could be resolved. Set it "
              "in one of these ways (checked in this order):")
        print("  1. pass it explicitly:  -- --blend <path-to-character.blend>")
        print("  2. the RC_CHARACTER environment variable")
        print("  3. the RC_MPFB_ROOT default: <RC_MPFB_ROOT>\\tmp\\character.blend "
              "(create the character once in Blender with MPFB2)")
        return EXIT_NO_BLEND
    if not _mpfb._mpfb_installed():
        print(f"MPFB LIVE SKIPPED: MPFB2 ({MPFB_MODULE}) is not installed in "
              "this Blender configuration.")
        print(ENV_HINT)
        return EXIT_NO_MPFB

    if args["mode"] == "self_test":
        return mode_self_test(args["channel"], args["value"], blend_path)
    if args["mode"] == "sweep":
        sweep_value = args["value"] if args["value_given"] else SWEEP_DRIVE_VALUE
        return mode_sweep(sweep_value, blend_path)
    if args["poses"]:
        return mode_pose(args["poses"], blend_path)
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

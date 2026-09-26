"""Interactive live demo: a real Blender window whose face visibly deforms
through the RealCapture addon's own apply path.

Run from the repository root:

  GUI autonomous demo (no camera, no backend, no downloads):
      "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
          --python tools/blender_live_demo.py -- --self-drive

  GUI driven by a real backend streaming ARKit packets (default when
  --self-drive is absent):
      "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" \
          --python tools/blender_live_demo.py --
      # UDP on port 11111 (override with --port <n>)

  Headless self-test (deterministic ticks + coordinate table + assertions):
      "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" -b \
          --python tools/blender_live_demo.py -- --self-test

  Headless render of the deformed state:
      "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" -b \
          --python tools/blender_live_demo.py -- --render soak_output/live_demo.png

Why this exists: shape_key_add() alone creates a key identical to Basis, so a
synthetic rig with empty key data cannot move. This demo writes real
per-vertex offsets into key_block.data[i].co for every key, then drives the
REAL consumer apply path (CaptureConsumer._apply -> FacePointRig.apply) so the
deformation pipeline exercised on stage is the one the addon ships.

Non-blocking by design: live modes use bpy.app.timers callbacks; there is no
blocking `while True` pump (which would freeze a GUI window).
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import bpy  # noqa: E402

import addon  # noqa: E402  (loaded by path, never installed)

BLENDER_EXE = "C:/Program Files/Blender Foundation/Blender 4.5/blender.exe"

# Real ARKit channel names (addon/rigprofile/channels.py ARKIT_CHANNELS).
DEMO_CHANNELS: tuple[str, ...] = (
    "jawOpen", "mouthSmileLeft", "mouthSmileRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "browOuterUpLeft", "browOuterUpRight", "mouthPucker",
)

# Deterministic target expression for --self-test / --render.
TARGET_EXPRESSION = {
    "jawOpen": 0.80,
    "mouthSmileLeft": 0.70,
    "mouthSmileRight": 0.50,
    "eyeBlinkLeft": 1.00,
    "eyeBlinkRight": 0.60,
    "browOuterUpLeft": 0.90,
    "browOuterUpRight": 0.40,
    "mouthPucker": 0.55,
}
SELF_TEST_TICKS = 10
MOVE_THRESHOLD = 0.005  # min |current - basis| (Blender units) for a key to count as deforming

# -- face geometry ------------------------------------------------------------

GRID_X, GRID_Z = 19, 17           # subdivisions (grid is (GRID_X * GRID_Z) verts)
HALF_W, HALF_H = 0.65, 0.85       # half extents of the face plane
FACE_Y_BULGE = 0.10               # how far the face center bulges toward camera

EYE_Z, EYE_X, EYE_R = 0.30, 0.26, 0.14
BROW_Z, BROW_X, BROW_R = 0.55, 0.30, 0.22
CORNER_X, CORNER_Z, CORNER_R = 0.20, -0.12, 0.16
MOUTH_X, MOUTH_Z, MOUTH_R = 0.00, -0.08, 0.20


def _falloff(dist: float, radius: float) -> float:
    if dist >= radius:
        return 0.0
    t = 1.0 - dist / radius
    return t * t


def _channel_weight(channel: str, x: float, z: float) -> float:
    """Plausible per-vertex influence [0, 1] of one ARKit channel."""
    if channel == "jawOpen":
        return min(1.0, (-0.30 - z) / 0.35) if z < -0.30 else 0.0
    if channel == "mouthPucker":
        return _falloff(math.hypot(x - MOUTH_X, z - MOUTH_Z), MOUTH_R)
    if channel == "mouthSmileLeft":
        return _falloff(math.hypot(x + CORNER_X, z - CORNER_Z), CORNER_R)
    if channel == "mouthSmileRight":
        return _falloff(math.hypot(x - CORNER_X, z - CORNER_Z), CORNER_R)
    if channel == "eyeBlinkLeft":
        return _falloff(math.hypot(x + EYE_X, z - EYE_Z), EYE_R)
    if channel == "eyeBlinkRight":
        return _falloff(math.hypot(x - EYE_X, z - EYE_Z), EYE_R)
    if channel == "browOuterUpLeft":
        return _falloff(math.hypot(x + BROW_X, z - BROW_Z), BROW_R)
    if channel == "browOuterUpRight":
        return _falloff(math.hypot(x - BROW_X, z - BROW_Z), BROW_R)
    return 0.0


def _channel_offset(channel: str, x: float, y: float, z: float) -> tuple[float, float, float]:
    """World-space displacement of one vertex for this channel at full value.

    jaw lowers, mouth corners rise, eyelids close toward the eye line, brows
    lift, lips pull forward and toward the mouth center (pucker).
    """
    w = _channel_weight(channel, x, z)
    if w <= 0.0:
        return (0.0, 0.0, 0.0)
    if channel == "jawOpen":
        return (0.0, -0.04 * w, -0.26 * w)
    if channel == "mouthPucker":
        return ((MOUTH_X - x) * 0.45 * w, -0.07 * w, (MOUTH_Z - z) * 0.45 * w)
    if channel == "mouthSmileLeft":
        return (-0.05 * w, 0.0, 0.10 * w)
    if channel == "mouthSmileRight":
        return (0.05 * w, 0.0, 0.10 * w)
    if channel in ("eyeBlinkLeft", "eyeBlinkRight"):
        return (0.0, 0.0, -0.07 * w)  # eyelid drops: visible blink
    if channel in ("browOuterUpLeft", "browOuterUpRight"):
        return (0.0, 0.0, 0.09 * w)
    return (0.0, 0.0, 0.0)


def _face_vertex(i: int, j: int) -> tuple[float, float, float]:
    x = -HALF_W + i * (2.0 * HALF_W / (GRID_X - 1))
    z = -HALF_H + j * (2.0 * HALF_H / (GRID_Z - 1))
    y = -FACE_Y_BULGE * max(0.0, 1.0 - (x / HALF_W) ** 2) * max(0.0, 1.0 - (z / HALF_H) ** 2)
    return (x, y, z)


def clear_startup_scene() -> None:
    """Remove objects from the startup file (default Cube/Camera/Light) so the
    demo window shows exactly the RealCapture face stage."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def build_face_mesh() -> bpy.types.Object:
    """Crude face-like grid with REAL per-vertex shape key offsets."""
    verts = [_face_vertex(i, j) for j in range(GRID_Z) for i in range(GRID_X)]
    faces = []
    for j in range(GRID_Z - 1):
        for i in range(GRID_X - 1):
            a = j * GRID_X + i
            faces.append((a, a + 1, a + GRID_X + 1, a + GRID_X))

    mesh_data = bpy.data.meshes.new("LiveDemoFace")
    mesh_data.from_pydata(verts, [], faces)
    mesh_obj = bpy.data.objects.new("LiveDemoFace", mesh_data)
    bpy.context.scene.collection.objects.link(mesh_obj)

    basis = mesh_obj.shape_key_add(name="Basis", from_mix=False)
    for channel in DEMO_CHANNELS:
        key = mesh_obj.shape_key_add(name=channel, from_mix=False)
        key.relative_key = basis
        key.value = 0.0
        for idx, (x, y, z) in enumerate(verts):
            dx, dy, dz = _channel_offset(channel, x, y, z)
            key.data[idx].co = (x + dx, y + dy, z + dz)
    return mesh_obj


def build_stage(mesh_obj: bpy.types.Object) -> None:
    """Camera, lights, material and a minimal armature so bind_rig can run."""
    # Minimal armature (head bone only): the wizard requires one to bind.
    arm_data = bpy.data.armatures.new("LiveDemoRig")
    arm_obj = bpy.data.objects.new("LiveDemoRig", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    head = arm_data.edit_bones.new("head")
    head.head, head.tail = (0.0, -0.1, 0.0), (0.0, 0.0, 0.15)
    bpy.ops.object.mode_set(mode="OBJECT")

    controller = bpy.data.objects.new("RealCapture_Controller", None)
    bpy.context.scene.collection.objects.link(controller)

    # Material: crude skin tone so the face reads on screen.
    mat = bpy.data.materials.new("LiveDemoSkin")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.72, 0.52, 0.42, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.6
    mesh_obj.data.materials.append(mat)

    # Camera looking at the face from the front (+Y direction of view).
    cam_data = bpy.data.cameras.new("LiveDemoCamera")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("LiveDemoCamera", cam_data)
    cam.location = (0.0, -2.4, 0.05)
    cam.rotation_euler = (math.radians(88.0), 0.0, 0.0)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    # Lights: warm key + soft fill (point lights need no aiming).
    for name, loc, energy, color in (
        ("LiveDemoKey", (0.9, -1.3, 1.3), 300.0, (1.0, 0.95, 0.88)),
        ("LiveDemoFill", (-1.1, -1.5, 0.2), 90.0, (0.75, 0.82, 1.0)),
    ):
        light_data = bpy.data.lights.new(name, type="POINT")
        light_data.energy = energy
        light_data.color = color
        light_obj = bpy.data.objects.new(name, light_data)
        light_obj.location = loc
        bpy.context.scene.collection.objects.link(light_obj)

    world = bpy.data.worlds.get("LiveDemoWorld") or bpy.data.worlds.new("LiveDemoWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.04, 0.04, 0.06, 1.0)
    bpy.context.scene.world = world


def setup_and_bind(profile_path: str) -> bpy.types.Object:
    """Build the scene, register the addon by path, scan + bind the real rig."""
    clear_startup_scene()
    mesh_obj = build_face_mesh()
    build_stage(mesh_obj)

    addon.register()

    scene = bpy.context.scene
    settings = scene.realcapture
    settings.controller = bpy.data.objects["RealCapture_Controller"]
    settings.rig_face_mesh = bpy.data.objects["LiveDemoFace"]
    settings.rig_armature = bpy.data.objects["LiveDemoRig"]
    settings.rig_profile_path = profile_path

    result = bpy.ops.realcapture.scan_rig()
    assert result == {"FINISHED"}, "scan_rig failed"
    result = bpy.ops.realcapture.bind_rig()
    assert result == {"FINISHED"}, "bind_rig failed"
    return mesh_obj


# -- packet manufacture (make_packet pattern from blender_smoke_test.py) ------

def make_packet(shapes: dict[str, float], engine: str = "demo", conf: float = 0.95):
    packet = type("Packet", (), {})()
    packet.t = int(time.time() * 1000)
    packet.engine = engine
    packet.conf = conf
    packet.pose = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}
    packet.shapes = shapes
    packet.extra = {}
    return packet


def ramp_shapes(tick: int, total: int) -> dict[str, float]:
    f = min(1.0, tick / max(1, total))
    return {ch: target * f for ch, target in TARGET_EXPRESSION.items()}


# -- evaluation helpers ---------------------------------------------------------

def evaluated_coords(mesh_obj: bpy.types.Object) -> list[tuple[float, float, float]]:
    """Current (shape-key-applied) vertex coordinates from the depsgraph."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = mesh_obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()
    coords = [tuple(v.co) for v in mesh_eval.vertices]
    obj_eval.to_mesh_clear()
    return coords


def verify_table(mesh_obj: bpy.types.Object) -> tuple[list[tuple], list[str]]:
    """Per-channel table rows and failing-channel names for the self-test."""
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    basis_block = key_blocks["Basis"]
    current = evaluated_coords(mesh_obj)

    rows: list[tuple] = []
    failures: list[str] = []
    print(f"\n{'channel':<18} {'value':>6}  {'basis coord (x,y,z)':<30} "
          f"{'current coord (x,y,z)':<30} {'delta':>7}  vert")
    for channel in DEMO_CHANNELS:
        key = key_blocks[channel]
        # Representative vertex: strongest displacement for this channel.
        rep, best = 0, -1.0
        for idx, vert in enumerate(basis_block.data):
            x, y, z = vert.co
            dx, dy, dz = _channel_offset(channel, x, y, z)
            mag = math.sqrt(dx * dx + dy * dy + dz * dz)
            if mag > best:
                best, rep = mag, idx
        b = tuple(basis_block.data[rep].co)
        c = current[rep]
        delta = math.dist(b, c)
        controlled = [
            i for i in range(len(basis_block.data))
            if _channel_offset(channel, *basis_block.data[i].co) != (0.0, 0.0, 0.0)
        ]
        max_delta = max(
            (math.dist(tuple(basis_block.data[i].co), current[i]) for i in controlled),
            default=0.0,
        )
        value_ok = abs(key.value) > 1e-6
        move_ok = max_delta > MOVE_THRESHOLD
        rows.append((channel, key.value, b, c, delta, rep))
        print(f"{channel:<18} {key.value:6.3f}  ({b[0]:+7.4f},{b[1]:+7.4f},{b[2]:+7.4f})      "
              f"({c[0]:+7.4f},{c[1]:+7.4f},{c[2]:+7.4f})      {delta:7.4f}  #{rep}")
        if not value_ok:
            failures.append(f"{channel}: shape key value stayed zero ({key.value:.4f})")
        if not move_ok:
            failures.append(
                f"{channel}: no vertex moved relative to Basis "
                f"(max delta {max_delta:.6f} <= {MOVE_THRESHOLD})")
    return rows, failures


# -- modes ----------------------------------------------------------------------

def mode_self_test() -> int:
    from addon.ui import _get_consumer

    profile_path = os.path.join(tempfile.gettempdir(), "rc_live_demo_profile.json")
    mesh_obj = setup_and_bind(profile_path)
    consumer = _get_consumer()

    for tick in range(1, SELF_TEST_TICKS + 1):
        consumer._apply(make_packet(ramp_shapes(tick, SELF_TEST_TICKS)))

    _rows, failures = verify_table(mesh_obj)

    if failures:
        for failure in failures:
            print(f"FAILED CHANNEL: {failure}")
        print("LIVE DEMO SELF-TEST FAILED")
        return 1
    print(f"\nAll {len(DEMO_CHANNELS)} shape keys received non-zero values and "
          "deformed vertices away from Basis.")
    print("LIVE DEMO SELF-TEST PASSED")
    return 0


def mode_render(render_arg: str) -> int:
    from addon.ui import _get_consumer

    profile_path = os.path.join(tempfile.gettempdir(), "rc_live_demo_profile.json")
    mesh_obj = setup_and_bind(profile_path)
    consumer = _get_consumer()
    consumer._apply(make_packet(TARGET_EXPRESSION))

    out_path = render_arg if os.path.isabs(render_arg) else os.path.join(REPO_ROOT, render_arg)
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 48
    scene.render.resolution_x = 800
    scene.render.resolution_y = 600
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)

    _rows, failures = verify_table(mesh_obj)
    if failures:
        for failure in failures:
            print(f"FAILED CHANNEL: {failure}")
        return 1
    print(f"RENDER WRITTEN: {out_path}")
    return 0


_DRIVE_INTERVAL = 1.0 / 30.0


def mode_self_drive() -> int:
    from addon.ui import _get_consumer

    profile_path = os.path.join(tempfile.gettempdir(), "rc_live_demo_profile.json")
    mesh_obj = setup_and_bind(profile_path)
    consumer = _get_consumer()

    def drive_tick() -> float:
        t = time.monotonic()
        shapes = {
            "jawOpen": 0.45 + 0.45 * math.sin(t * 1.1),
            "mouthPucker": 0.45 + 0.45 * math.sin(t * 0.9 + 1.0),
            "mouthSmileLeft": 0.5 + 0.5 * math.sin(t * 0.7 + 2.0),
            "mouthSmileRight": 0.5 + 0.5 * math.sin(t * 0.7 + 2.4),
            "eyeBlinkLeft": max(0.0, math.sin(t * 1.7) ** 8),
            "eyeBlinkRight": max(0.0, math.sin(t * 1.7) ** 8),
            "browOuterUpLeft": 0.5 + 0.5 * math.sin(t * 0.6 + 3.0),
            "browOuterUpRight": 0.5 + 0.5 * math.sin(t * 0.6 + 3.3),
        }
        consumer._apply(make_packet(shapes))
        return _DRIVE_INTERVAL

    bpy.app.timers.register(drive_tick, first_interval=0.5)
    print("=== RealCapture LIVE DEMO: self-drive mode ===")
    print("Autonomously animating", ", ".join(DEMO_CHANNELS))
    print("through the real consumer apply path. Close the Blender window to stop.")
    print(f"(Mesh: {mesh_obj.name}, camera: LiveDemoCamera. Press 0 / numpad 0 to view it.)")
    return 0


def mode_udp_listen(port: int) -> int:
    profile_path = os.path.join(tempfile.gettempdir(), "rc_live_demo_profile.json")
    mesh_obj = setup_and_bind(profile_path)

    from addon.ui import _get_consumer

    _get_consumer().start(port=port)
    print(f"=== RealCapture LIVE DEMO: UDP-listen mode on port {port} ===")
    print("Incoming ARKit packets now drive the face through the real consumer "
          "apply path (bpy.app.timers, non-blocking).")
    print(f"(Mesh: {mesh_obj.name}, camera: LiveDemoCamera. Press 0 / numpad 0 to view it.)")
    return 0


# -- entry ------------------------------------------------------------------------

def _parse_args() -> dict:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parsed: dict = {"mode": "udp", "port": 11111, "render_path": None}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--self-test":
            parsed["mode"] = "self_test"
        elif arg == "--self-drive":
            parsed["mode"] = "self_drive"
        elif arg == "--render":
            parsed["mode"] = "render"
            i += 1
            parsed["render_path"] = args[i] if i < len(args) else None
        elif arg == "--port":
            i += 1
            parsed["port"] = int(args[i]) if i < len(args) else 11111
        i += 1
    return parsed


def main() -> int:
    args = _parse_args()
    if args["mode"] == "self_test":
        return mode_self_test()
    if args["mode"] == "render":
        if not args["render_path"]:
            print("--render requires a path, e.g. --render soak_output/live_demo.png")
            return 2
        return mode_render(args["render_path"])
    if args["mode"] == "self_drive":
        return mode_self_drive()
    return mode_udp_listen(args["port"])


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"LIVE DEMO CRASHED: {exc}")
        code = 2
    background = "-b" in sys.argv or "--background" in sys.argv
    if background or code != 0:
        sys.exit(code)
    # GUI live modes: keep the window open (Blender continues after the script).

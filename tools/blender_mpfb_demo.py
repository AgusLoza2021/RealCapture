"""Real-rig demo: drive a real MPFB2 character through the RealCapture addon.

Unlike tools/blender_smoke_test.py (a synthetic 4-vertex quad) this harness
opens a .blend containing a real, downloaded/generated MPFB2 character,
binds the RealCapture scan -> bind workflow against it, feeds one capture
packet through the REAL consumer apply path, and reports which shape keys
actually moved away from Basis (with the controlled vertex index and delta).

The character is NOT committed to the repository. It is generated with MPFB2
into a temporary, isolated Blender configuration (factory startup + temp
BLENDER_USER_* dirs). One-time character generation (outside the repo):

    export BLENDER_USER_CONFIG=<tmp>/env/config \
           BLENDER_USER_SCRIPTS=<tmp>/env/scripts \
           BLENDER_USER_EXTENSIONS=<tmp>/env/extensions \
           BLENDER_USER_DATA=<tmp>/env/data
    blender -b --factory-startup --command extension install-file mpfb-2.0.8.zip --repo user_default
    blender -b --factory-startup --python gen_character.py   # creates character.blend

Run this harness (same env vars still exported):

    blender -b --factory-startup --python tools/blender_mpfb_demo.py -- \
        <path-to-character.blend> [--channel jawOpen] [--value 0.9]

Exit codes:
    0  assertion passed: a vertex moved away from Basis on the driven key
    1  assertion failed: no vertex moved relative to Basis / key value stayed zero
    2  unexpected error (operator failure, missing objects, ...)
    3  the given .blend path does not exist
    4  MPFB2 is not installed in this Blender configuration

Mutation proof: run again with `--value 0` (or `--channel notAnArKitChannel`);
the harness must exit 1 with a "no vertex moved relative to Basis" message.
"""

from __future__ import annotations

import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import bpy  # noqa: E402

EXIT_OK = 0
EXIT_ASSERT = 1
EXIT_ERROR = 2
EXIT_NO_BLEND = 3
EXIT_NO_MPFB = 4

MPFB_MODULE = "bl_ext.user_default.mpfb"  # manifest-extension namespace
ARKit_CHANNEL_SEEDS = ("jawOpen", "eyeBlinkLeft", "mouthSmileLeft")


def _import_live_demo():
    """Import tools/blender_live_demo.py (unmodified) to reuse its helpers."""
    path = os.path.join(REPO_ROOT, "tools", "blender_live_demo.py")
    spec = importlib.util.spec_from_file_location("blender_live_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_args() -> dict:
    argv = sys.argv
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    parsed: dict = {"blend": None, "channel": "jawOpen", "value": 0.9}
    positional: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--channel":
            i += 1
            parsed["channel"] = args[i]
        elif args[i] == "--value":
            i += 1
            parsed["value"] = float(args[i])
        else:
            positional.append(args[i])
        i += 1
    if positional:
        parsed["blend"] = positional[0]
    return parsed


def _mpfb_installed() -> bool:
    """True only if the MPFB2 extension can actually be enabled."""
    import addon_utils

    try:
        # default_set=True is required: MPFB's register() reads its own
        # preferences, which only exist once the addon is in preferences.
        return addon_utils.enable(MPFB_MODULE, default_set=True) is not None
    except Exception:  # noqa: BLE001 - any failure means "not usable"
        return False


def _open_blend(path: str) -> None:
    bpy.ops.wm.open_mainfile(filepath=path)


def _find_face_mesh() -> bpy.types.Object | None:
    """A mesh whose shape keys carry the ARKit face-unit names (MPFB head)."""
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data.shape_keys:
            continue
        names = {k.name for k in obj.data.shape_keys.key_blocks}
        if all(seed in names for seed in ARKit_CHANNEL_SEEDS):
            return obj
    return None


def _find_armature() -> tuple[bpy.types.Object | None, str | None]:
    """The MPFB armature plus its head bone (lowercase prefix 'head')."""
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE":
            continue
        for bone in obj.data.bones:
            if bone.name.lower().startswith("head"):
                return obj, bone.name
    return None, None


def _controlled_vertices(key_block) -> set[int]:
    """Indices where this key's data differs from Basis."""
    basis = key_block.relative_key or key_block.id_data.key_blocks[0]
    return {
        i for i in range(len(basis.data))
        if (key_block.data[i].co - basis.data[i].co).length > 1e-9
    }


def _max_move(mesh_obj, indices: set[int], baseline: list) -> tuple[int, float]:
    """(vertex index, |current - baseline|) of the strongest moved vertex."""
    live = _live_coords(mesh_obj)
    best_i, best_d = -1, 0.0
    for i in indices:
        d = (live[i] - baseline[i]).length
        if d > best_d:
            best_i, best_d = i, d
    return best_i, best_d


def _live_coords(mesh_obj) -> list:
    """Evaluated (shape-key-applied) coordinates, one entry per base vertex.

    Viewport modifiers (MPFB uses a Mask modifier to hide helper vertices)
    are disabled around the evaluation so vertex indices stay aligned with
    the shape key data; the modifiers are restored afterwards.
    """
    hidden = [(mod, mod.show_viewport) for mod in mesh_obj.modifiers]
    for mod, _ in hidden:
        mod.show_viewport = False
    try:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj_eval = mesh_obj.evaluated_get(depsgraph)
        mesh_eval = obj_eval.to_mesh()
        coords = [v.co.copy() for v in mesh_eval.vertices]
        obj_eval.to_mesh_clear()
    finally:
        for mod, was_visible in hidden:
            mod.show_viewport = was_visible
    return coords


def main() -> int:
    args = _parse_args()

    # -- self-guards: one clear line, distinct code, never a traceback ------
    if not args["blend"] or not os.path.isfile(args["blend"]):
        print(f"MPFB DEMO SKIPPED: .blend not found: {args['blend']!r} "
              "(pass a generated MPFB character .blend after '--')")
        return EXIT_NO_BLEND
    if not _mpfb_installed():
        print(f"MPFB DEMO SKIPPED: MPFB2 ({MPFB_MODULE}) is not installed in this "
              "Blender configuration; install it into the isolated config first")
        return EXIT_NO_MPFB

    live = _import_live_demo()
    make_packet = live.make_packet
    threshold = live.MOVE_THRESHOLD

    _open_blend(args["blend"])

    mesh_obj = _find_face_mesh()
    armature, head_bone = _find_armature()
    if mesh_obj is None or armature is None:
        print(f"MPFB DEMO FAILED: no MPFB face mesh / armature with a head bone in "
              f"{args['blend']} (mesh={mesh_obj}, armature={armature})")
        return EXIT_ERROR

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

    # -- real scan -> bind ---------------------------------------------------
    result = bpy.ops.realcapture.scan_rig()
    if result != {"FINISHED"}:
        print("MPFB DEMO FAILED: scan_rig did not finish")
        return EXIT_ERROR
    proposals = [it for it in settings.rig_proposals if it.kind == "shapekey"]
    exact = [it for it in proposals if it.confidence >= 1.0]
    print(f"SCAN: {len(proposals)} shape-key proposals "
          f"({len(exact)} exact-confidence)")

    result = bpy.ops.realcapture.bind_rig()
    if result != {"FINISHED"}:
        print("MPFB DEMO FAILED: bind_rig did not finish "
              "(see operator report above)")
        return EXIT_ERROR

    # -- one packet through the real consumer apply path ---------------------
    from addon.ui import _get_consumer

    consumer = _get_consumer()
    driven = list(mesh_obj.get("rc_driven_shapekeys", []))
    key_blocks = mesh_obj.data.shape_keys.key_blocks
    print(f"BOUND KEYS: {driven}")

    baseline = _live_coords(mesh_obj)
    consumer._apply(make_packet({args["channel"]: args["value"]}))
    live_coords = _live_coords(mesh_obj)

    # -- report which shape keys actually moved away from Basis --------------
    moved: list[str] = []
    failures: list[str] = []
    target_key = key_blocks.get(args["channel"])
    print(f"\n{'key':<24} {'value':>6}  {'vert':>7}  {'delta':>8}")
    for name in driven:
        key = key_blocks.get(name)
        if key is None:
            continue
        indices = _controlled_vertices(key)
        vert, delta = _max_move(mesh_obj, indices, baseline)
        mark = " <- fed" if name == args["channel"] else ""
        print(f"{name:<24} {key.value:6.3f}  #{vert:<6d} {delta:8.4f}{mark}")
        if delta > threshold and vert >= 0:
            moved.append(name)

    if target_key is not None and abs(target_key.value - args["value"]) > 1e-4:
        failures.append(
            f"{args['channel']}: value did not reach the packet value "
            f"({target_key.value:.4f} != {args['value']:.4f})")
    if target_key is None or not (
            args["channel"] in moved and _max_move(
                mesh_obj, _controlled_vertices(target_key), baseline)[1] > threshold):
        failures.append(
            f"no vertex moved relative to Basis on '{args['channel']}' "
            "(controlled vertices unchanged)")
    if not moved:
        failures.append("no vertex moved relative to Basis (scene unchanged)")

    if failures:
        for failure in failures:
            print(f"FAILED: {failure}")
        print("MPFB DEMO FAILED")
        return EXIT_ASSERT

    total_delta = max(
        (live_coords[i] - baseline[i]).length for i in range(len(baseline)))
    print(f"\nMoved keys: {moved}")
    print(f"Driven '{args['channel']}'={args['value']}: strongest total vertex "
          f"displacement {total_delta:.4f} Blender units.")
    print("MPFB DEMO PASSED")
    return EXIT_OK


if __name__ == "__main__":
    try:
        _code = main()
    except Exception as exc:  # noqa: BLE001 - guards above are one-line;
        # unexpected failures deserve full diagnosis
        import traceback

        traceback.print_exc()
        print(f"MPFB DEMO ERROR: {exc}")
        _code = EXIT_ERROR
    sys.exit(_code)

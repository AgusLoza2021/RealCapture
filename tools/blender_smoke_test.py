"""Headless Blender smoke test for the RealCapture addon + Rig Connector.

Run with:  blender -b --python tools/blender_smoke_test.py

Builds a synthetic face rig, registers the addon, runs the full wizard
(scan -> bind), drives packets through the consumer, evaluates drivers via the
depsgraph, verifies face-point movement, and unbinds. Exits non-zero on any
check failure.
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

from addon import binding  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def build_scene() -> None:
    # Armature: head + jaw + eyelid + brow bones (Rigify-ish names).
    arm_data = bpy.data.armatures.new("FaceRig")
    arm_obj = bpy.data.objects.new("FaceRig", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_data.edit_bones
    head = edit_bones.new("head")
    head.head, head.tail = (0, -0.1, 0), (0, 0, 0.15)
    for name, tail in (("jaw", (0, 0.05, -0.1)), ("eyelid.T.L", (0.03, 0.08, 0.06)),
                       ("brow.B.L", (0.03, 0.09, 0.08))):
        bone = edit_bones.new(name)
        bone.head, bone.tail = (0, 0, 0.1), tail
        bone.parent = head
    bpy.ops.object.mode_set(mode="OBJECT")

    # Mesh with ARKit shape keys.
    mesh_data = bpy.data.meshes.new("FaceMesh")
    mesh_obj = bpy.data.objects.new("FaceMesh", mesh_data)
    bpy.context.scene.collection.objects.link(mesh_obj)
    verts = [(-0.1, -0.1, 0), (0.1, -0.1, 0), (0.1, 0.1, 0), (-0.1, 0.1, 0)]
    mesh_data.from_pydata(verts, [], [[0, 1, 2, 3]])
    mesh_obj.shape_key_add(name="Basis")
    for channel in ("jawOpen", "eyeBlinkLeft", "eyeBlinkRight", "mouthSmileLeft",
                    "browOuterUpLeft", "Eye_Wide"):
        mesh_obj.shape_key_add(name=channel)

    # Controller empty.
    controller = bpy.data.objects.new("RealCapture_Controller", None)
    bpy.context.scene.collection.objects.link(controller)


def register_addon() -> None:
    from addon import properties, ui, wizard

    properties.register()
    wizard.register()
    ui.register()


def make_packet(shapes: dict[str, float], conf: float = 0.9):
    packet = type("Packet", (), {})()
    packet.t = int(time.time() * 1000)
    packet.engine = "smoke"
    packet.conf = conf
    packet.pose = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}
    packet.shapes = shapes
    packet.extra = {}
    return packet


def main() -> int:
    print("=== RealCapture Blender smoke test ===")
    build_scene()
    register_addon()

    scene = bpy.context.scene
    settings = scene.realcapture
    settings.controller = bpy.data.objects["RealCapture_Controller"]
    settings.rig_face_mesh = bpy.data.objects["FaceMesh"]
    settings.rig_armature = bpy.data.objects["FaceRig"]
    settings.rig_profile_path = os.path.join(tempfile.gettempdir(), "rc_smoke_profile.json")

    # --- Wizard: scan + bind -----------------------------------------------
    result = bpy.ops.realcapture.scan_rig()
    check("scan_rig executes", result == {"FINISHED"})
    proposals = list(settings.rig_proposals)
    check("scan found proposals", len(proposals) >= 4, f"{len(proposals)} proposals")
    keys = {p.key for p in proposals}
    check("jawOpen matched", "jawOpen" in keys, str(sorted(keys)[:6]))

    result = bpy.ops.realcapture.bind_rig()
    check("bind_rig executes", result == {"FINISHED"})

    empties = [o for o in bpy.data.collections.get(binding.POINTS_COLLECTION).objects]
    check("face point empties created", len(empties) >= 1,
          f"{len(empties)} empties: {[e.name for e in empties][:4]}")
    jaw_bone = bpy.data.objects["FaceRig"].pose.bones["jaw"]
    cons = [c for c in jaw_bone.constraints if c.name.startswith(binding.CONSTRAINT_PREFIX)]
    check("bone constraint created", len(cons) == 1)

    key_blocks = bpy.data.objects["FaceMesh"].data.shape_keys.key_blocks
    check("shape keys marked as bound",
          "eyeBlinkLeft" in bpy.data.objects["FaceMesh"].get(binding.DRIVEN_PROP, []))

    # --- Consumer applies packets ------------------------------------------
    from addon.ui import _get_consumer

    consumer = _get_consumer()
    consumer._apply(make_packet({"jawOpen": 1.0, "eyeBlinkLeft": 0.5, "eyeWide": 0.8}))
    # Force a depsgraph evaluation cycle so drivers re-run (they evaluate on
    # frame changes; view_layer.update() alone does not re-run drivers).
    bpy.context.scene.frame_set(1)
    bpy.context.scene.frame_set(2)

    controller = settings.controller
    check("controller shape prop written",
          abs(controller.get("rc_shape_jawOpen", -1) - 1.0) < 1e-6,
          f"rc_shape_jawOpen={controller.get('rc_shape_jawOpen')}")
    check("controller meta written", controller.get("rc_meta_engine") == "smoke")

    value = key_blocks["jawOpen"].value
    check("shape key jawOpen written directly", abs(value - 1.0) < 1e-4,
          f"value={value:.4f}")
    value = key_blocks["eyeBlinkLeft"].value
    check("shape key eyeBlinkLeft written directly", abs(value - 0.5) < 1e-4,
          f"value={value:.4f}")

    jaw_empty = bpy.data.objects.get(binding.EMPTY_PREFIX + "jaw")
    check("jaw point exists", jaw_empty is not None)
    if jaw_empty is not None:
        rest = list(jaw_empty["rc_rest_loc"])
        dz = jaw_empty.location.z - rest[2]
        check("jaw point moved by jawOpen", abs(dz - (-0.05)) < 1e-4, f"dz={dz:.4f}")

    # --- Unbind ---------------------------------------------------------------
    result = bpy.ops.realcapture.unbind_rig()
    check("unbind executes", result == {"FINISHED"})
    check("empties removed",
          bpy.data.collections.get(binding.POINTS_COLLECTION) is None)
    cons = [c for c in jaw_bone.constraints if c.name.startswith(binding.CONSTRAINT_PREFIX)]
    check("constraints removed", len(cons) == 0)
    drivers = key_blocks["eyeBlinkLeft"].id_data.animation_data.drivers         if key_blocks["eyeBlinkLeft"].id_data.animation_data else []
    check("legacy drivers removed", len(drivers) == 0)
    check("driven marker cleared",
          not bpy.data.objects["FaceMesh"].get(binding.DRIVEN_PROP))

    # --- Save/load profile -----------------------------------------------------
    bpy.ops.realcapture.scan_rig()
    bpy.ops.realcapture.bind_rig()
    from addon.rigprofile.profile import RigProfile

    profile = RigProfile.load(settings.rig_profile_path)
    check("profile saved & reloadable", profile.name != "" and
          (profile.shapekey_bindings or profile.bone_bindings))

    failures = [c for c in CHECKS if not c[1]]
    print(f"\n=== {len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed ===")
    for name, ok, detail in failures:
        print(f"FAILED: {name} {detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"SMOKE TEST CRASHED: {exc}")
        code = 2
    sys.exit(code)

"""Blender binding layer: turns a RigProfile into native Blender links.

Everything here touches bpy and must run on the main thread (timer callbacks
or operators). Design note: shape key values are written DIRECTLY by the
capture consumer each tick (no f-curve drivers) — Blender 4.x does not build
depsgraph dependencies for drivers whose target custom property is created
after the driver, which made driver-based binding unreliable. Bone following
stays native: COPY_LOCATION/COPY_ROTATION constraints toward the FPD empties,
fully inspectable and removable by artists. Unbind sweeps by our markers.

Naming/markers:
- FPD empties live in collection "RealCapture Points", named RC_pt_<role>.
- Bone constraints are named "RC_follow_<role>".
- Bound shape keys are listed in the mesh marker "rc_driven_shapekeys".
"""

from __future__ import annotations

from dataclasses import dataclass

import bpy
from mathutils import Vector

from .rigprofile.headbone import (
    choose_head_bone, exceeds_rest_gate, highest_head_candidate,
    is_gate_measurable)
from .rigprofile.profile import BoneBinding, RigProfile

POINTS_COLLECTION = "RealCapture Points"
EMPTY_PREFIX = "RC_pt_"
CONSTRAINT_PREFIX = "RC_follow_"
DRIVEN_PROP = "rc_driven_shapekeys"  # mesh-object marker: list of driven key names

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


class BindingError(RuntimeError):
    """Raised when a profile cannot be applied to the current scene."""


@dataclass
class BindReport:
    """What bind_profile actually did — the operator reports from this.

    bone_path_active is False with a skip_reason set, the bind produced NO
    bone path and callers must never present it as a full success.
    """

    bone_path_active: bool = False
    # "no_armature" | "no_head_bone" | "rest_gate"; None when the bone
    # path is live or the profile has no points/bone bindings at all.
    skip_reason: str | None = None
    head_bone: str | None = None
    head_bone_explicit: bool = False   # True when profile.head_bone was set
    rejected_bone: str | None = None   # highest 'head*' candidate when refused
    rejected_z: float | None = None
    mesh_z_min: float | None = None
    mesh_z_max: float | None = None
    rest_gate_fired: bool = False
    rest_displacement: float | None = None   # measured vs Basis, all shapes at 0
    rest_gate_mesh: str | None = None
    # Residual after a rejected bind was reverted: 0.0 means the revert
    # really undid the bind. Measured, never assumed.
    rest_displacement_after: float | None = None


class FacePointRig:
    """Runtime handle over the FPD empties and bound shape keys.

    Called by the consumer each tick. Transform entries accumulate per empty
    (rest + sum(deltas)); shape key values are written directly from the
    packet channels. All writes are epsilon-gated to avoid depsgraph churn.
    """

    def __init__(self, entries: dict[str, list[dict]],
                 shape_entries: list[dict] | None = None,
                 bind_report: BindReport | None = None) -> None:
        # entries[empty_name] = list of {kind, axis, gain, invert}
        self._entries = entries
        # shape_entries = list of {key_block, channel, gain, invert}
        self._shape_entries = shape_entries or []
        # Honest outcome of the bind (see BindReport); None for handles
        # built outside bind_profile.
        self.bind_report = bind_report

    @property
    def empty_names(self) -> list[str]:
        return list(self._entries)

    def apply(self, packet) -> None:  # noqa: ANN001 - schema.Packet
        values = packet.shapes
        for entry in self._shape_entries:
            key_block = entry["key_block"]
            value = values.get(entry["channel"])
            if value is None:
                continue
            target = entry["gain"] * (-value if entry["invert"] else value)
            if abs(key_block.value - target) > 1e-4:
                key_block.value = target
        for empty_name, transforms in self._entries.items():
            empty = bpy.data.objects.get(empty_name)
            if empty is None:
                continue  # deleted by the user: skip silently
            delta_loc = [0.0, 0.0, 0.0]
            delta_rot = [0.0, 0.0, 0.0]
            for tr in transforms:
                value = values.get(tr["channel"])
                if value is None:
                    continue
                delta = tr["gain"] * (-value if tr["invert"] else value)
                if tr["kind"] == "location":
                    delta_loc[_AXIS_INDEX[tr["axis"]]] += delta
                else:
                    delta_rot[_AXIS_INDEX[tr["axis"]]] += delta

            rest_loc = empty.get("rc_rest_loc")
            rest_rot = empty.get("rc_rest_rot")
            if rest_loc is not None:
                self._write_axis(empty, "location", delta_loc, rest_loc, empty_name, "loc")
            if rest_rot is not None:
                self._write_axis(empty, "rotation_euler", delta_rot, rest_rot,
                                 empty_name, "rot")

    def _write_axis(self, empty, attr: str, deltas, rests, empty_name: str, tag: str) -> None:
        vec = getattr(empty, attr)
        for i, delta in enumerate(deltas):
            target = rests[i] + delta
            if abs(vec[i] - target) > 1e-6:
                vec[i] = target


def bind_profile(profile: RigProfile, controller, meshes, armature) -> FacePointRig:  # noqa: ANN001
    """Apply a full profile to the scene. Returns the runtime face-point rig.

    The point/bone path needs a geometrically plausible head bone (defect
    T9: a chest-height 'head' bone tore real characters apart). When none
    qualifies, the bind falls back to shape keys only instead of guessing;
    the returned rig's ``bind_report`` says what happened and why.
    """
    unbind_all()
    report = BindReport()

    head_bone: str | None = None
    if profile.points or profile.bone_bindings:
        if armature is None:
            report.skip_reason = "no_armature"
        else:
            head_bone, guess_info = _resolve_head_bone(profile, armature, meshes)
            report.head_bone = head_bone
            report.head_bone_explicit = bool(profile.head_bone)
            report.mesh_z_min = guess_info.get("mesh_z_min")
            report.mesh_z_max = guess_info.get("mesh_z_max")
            report.rejected_bone = guess_info.get("rejected_bone")
            report.rejected_z = guess_info.get("rejected_z")
            if head_bone is None:
                report.skip_reason = "no_head_bone"

    empty_by_role: dict[str, str] = {}
    if head_bone is not None:
        empty_by_role = _create_empties(profile, armature, head_bone)
        pose_snapshot = _snapshot_pose(armature)
        _bind_bones(profile, armature, empty_by_role)
        # Rest gate: measure what the bind does to the artifact with every
        # shape key at 0, and tear the point/bone path back down when the
        # damage is clearly broken.
        worst, worst_mesh = _measure_rest_displacement(meshes)
        if worst is not None:
            report.rest_displacement = worst
            report.rest_gate_mesh = worst_mesh
        if worst is not None and exceeds_rest_gate(worst):
            report.rest_gate_fired = True
            report.skip_reason = "rest_gate"
            _remove_point_bone_bindings(armature, pose_snapshot)
            empty_by_role = {}
            # A revert that leaves damage behind is not a revert: measure
            # the residual instead of asserting it is zero.
            residual, _ = _measure_rest_displacement(meshes)
            report.rest_displacement_after = residual
        else:
            report.bone_path_active = True

    shape_entries = _collect_shapekey_entries(profile, meshes)
    if head_bone is None and not shape_entries:
        # Nothing to bind at all: keep the previous hard failures.
        if armature is None:
            raise BindingError(
                "No armature: face points need a head to attach to")
        raise BindingError(
            "No head bone found; set 'head_bone' in the profile")

    # Accumulate transforms per empty for the runtime rig.
    entries: dict[str, list[dict]] = {name: [] for name in empty_by_role.values()}
    for tr in profile.points:
        empty_name = empty_by_role.get(tr.role)
        if empty_name is None:
            continue
        entries[empty_name].append({
            "channel": tr.channel, "kind": tr.kind, "axis": tr.axis,
            "gain": tr.gain, "invert": tr.invert,
        })
    return FacePointRig({k: v for k, v in entries.items() if v}, shape_entries,
                        bind_report=report)


def _resolve_head_bone(profile: RigProfile, armature, meshes):  # noqa: ANN001
    """Pick the head bone for the point path: (name or None, guess info).

    An explicit profile.head_bone is respected as-is (the rest gate below
    still checks the result); otherwise the guess is geometric (see
    _guess_head_bone) and a name-only match is refused.
    """
    if profile.head_bone:
        return profile.head_bone, {"source": "explicit"}
    return _guess_head_bone(armature, meshes)


# -- creation ----------------------------------------------------------------

def _create_empties(profile: RigProfile, armature, head_bone: str) -> dict[str, str]:  # noqa: ANN001
    """Create the FPD empties, parented to the vetted head bone.
    Returns role->empty name."""
    if armature is None:
        raise BindingError("No armature: face points need a head to attach to")
    if not head_bone:
        raise BindingError(
            "No head bone found; set 'head_bone' in the profile")

    collection = bpy.data.collections.get(POINTS_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(POINTS_COLLECTION)
        bpy.context.scene.collection.children.link(collection)

    roles = sorted({t.role for t in profile.points})
    mapping: dict[str, str] = {}
    for role in roles:
        name = EMPTY_PREFIX + role
        empty = bpy.data.objects.get(name)
        if empty is None:
            empty = bpy.data.objects.new(name, None)
            empty.empty_display_type = "SPHERE"
            empty.empty_display_size = 0.01
            collection.objects.link(empty)
            empty.parent = armature
            empty.parent_type = "BONE"
            empty.parent_bone = head_bone
            empty.location = _default_offset(role)
            empty.rotation_euler = (0.0, 0.0, 0.0)
        # Rest transforms are frozen at bind time; re-binding refreshes them.
        empty["rc_rest_loc"] = list(empty.location)
        empty["rc_rest_rot"] = list(empty.rotation_euler)
        mapping[role] = name
    return mapping


def _default_offset(role: str) -> tuple[float, float, float]:
    """Rough head-local placement. Artists reposition empties freely."""
    base = {"jaw": (0.0, 0.06, -0.10), "lip_top": (0.0, 0.09, 0.02),
            "lip_bottom": (0.0, 0.08, -0.02), "brow_inner": (0.0, 0.10, 0.06)}
    if role in base:
        return base[role]
    side_x = 0.03 if role.endswith(".L") else -0.03 if role.endswith(".R") else 0.0
    role_base = role.split(".")[0]
    offsets = {"eye": (side_x, 0.06, 0.03), "eye_lid": (side_x, 0.08, 0.03),
               "brow": (side_x, 0.10, 0.06), "mouth_corner": (side_x, 0.08, 0.0),
               "cheek": (side_x * 1.4, 0.07, 0.02)}
    return offsets.get(role_base, (0.0, 0.07, 0.0))


def _guess_head_bone(armature, meshes) -> tuple[str | None, dict]:  # noqa: ANN001
    """Geometric head-bone guess. Returns (bone name or None, diagnostic info).

    A bone is never accepted on its name alone (defect T9). Mesh vertical
    bounds come from each mesh object's ``bound_box`` corners transformed by
    ``matrix_world`` (chosen over Basis coordinates: bound_box needs no
    per-vertex iteration and covers the evaluated mesh). Each candidate's z
    is its highest world-space joint (max of head and tail), so a bone only
    counts as a head when its extent actually reaches the upper part of the
    mesh; the pure rule lives in rigprofile.headbone.choose_head_bone.
    """
    z_min, z_max = _mesh_z_bounds(meshes)
    info: dict = {"mesh_z_min": z_min, "mesh_z_max": z_max}
    if z_min is None or z_max is None:
        info["rejected_bone"] = None
        return None, info
    candidates: list[tuple[str, float]] = []
    for bone in armature.data.bones:
        z_head = (armature.matrix_world @ bone.head_local)[2]
        z_tail = (armature.matrix_world @ bone.tail_local)[2]
        candidates.append((bone.name, max(z_head, z_tail)))
    rejected = highest_head_candidate(candidates)
    info["rejected_bone"] = rejected[0] if rejected else None
    info["rejected_z"] = rejected[1] if rejected else None
    return choose_head_bone(candidates, z_min, z_max), info


def _mesh_z_bounds(meshes) -> tuple[float | None, float | None]:  # noqa: ANN001
    """Union of world-space vertical bounds of the given mesh objects."""
    z_min = z_max = None
    for mesh in meshes:
        if mesh.type != "MESH":
            continue
        for corner in mesh.bound_box:
            z = (mesh.matrix_world @ Vector(corner)).z
            z_min = z if z_min is None else min(z_min, z)
            z_max = z if z_max is None else max(z_max, z)
    return z_min, z_max


def _measure_rest_displacement(meshes) -> tuple[float | None, str | None]:  # noqa: ANN001
    """Worst vertex displacement vs Basis across the bound meshes.

    Measures the bind's own damage: every shape key value is forced to 0,
    the depsgraph is evaluated, and each evaluated vertex is compared with
    the Basis coordinate. Selection is order-independent on purpose (see
    is_gate_measurable): the first version keyed on the shape-key marker
    that this very bind writes later, so it measured an empty list, never
    fired, and the bind reported full success over a torn mesh. The
    evaluated mesh can be shorter than the Basis (modifiers); only the
    shared vertex prefix is compared. Returns (worst, mesh name) or
    (None, None) when there is nothing measurable.
    """
    bound = [m for m in meshes if is_gate_measurable(m)]
    if not bound:
        return None, None
    worst = 0.0
    worst_mesh: str | None = None
    for mesh in bound:
        key_blocks = _shape_keys_of(mesh)
        if key_blocks is None or "Basis" not in key_blocks:
            continue
        basis = key_blocks["Basis"]
        saved = [kb.value for kb in key_blocks]
        for key_block in key_blocks:
            key_block.value = 0.0
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = mesh.evaluated_get(depsgraph)
            eval_mesh = evaluated.to_mesh()
            if eval_mesh is None:
                continue
            try:
                basis_cos = [point.co for point in basis.data]
                count = min(len(eval_mesh.vertices), len(basis_cos))
                for i in range(count):
                    delta = (eval_mesh.vertices[i].co - basis_cos[i]).length
                    if delta > worst:
                        worst = delta
                        worst_mesh = mesh.name
            finally:
                evaluated.to_mesh_clear()
        finally:
            for key_block, value in zip(key_blocks, saved):
                key_block.value = value
    return worst, worst_mesh


def _snapshot_pose(armature) -> dict:  # noqa: ANN001
    """Remember every pose bone's basis so a rejected bind is reversible.

    Removing an RC_follow_* constraint is not enough to undo it: the
    constraint has already written the target offset into the pose bone's
    location, and the bone keeps it after the constraint is gone. Measured
    on the MPFB2 character, that leftover was 0.0621 m of mesh damage after
    teardown (down from 0.8319 m, but not the honest zero a "reverted"
    report implies).
    """
    return {pose_bone.name: pose_bone.matrix_basis.copy()
            for pose_bone in armature.pose.bones}


def _remove_point_bone_bindings(armature, pose_snapshot=None) -> None:  # noqa: ANN001
    """Tear down the point/bone path, keeping the shape-key binding.

    Restores the pose basis captured by :func:`_snapshot_pose` for every
    bone an RC_follow_* constraint was driving, so the mesh goes back to
    the state the operator had before the bind.
    """
    for pose_bone in armature.pose.bones:
        removed = False
        for constraint in [c for c in pose_bone.constraints
                           if c.name.startswith(CONSTRAINT_PREFIX)]:
            pose_bone.constraints.remove(constraint)
            removed = True
        if not removed or pose_snapshot is None:
            continue
        saved = pose_snapshot.get(pose_bone.name)
        if saved is not None:
            pose_bone.matrix_basis = saved
    collection = bpy.data.collections.get(POINTS_COLLECTION)
    if collection:
        for obj in [o for o in collection.objects]:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)


def _collect_shapekey_entries(profile: RigProfile, meshes) -> list[dict]:  # noqa: ANN001
    """Resolve shape key bindings to runtime entries written by the consumer.

    Values go straight to key_block.value each tick; no f-curve drivers (see
    module docstring). Any leftover RealCapture drivers from older versions
    are removed as cleanup.
    """
    entries: list[dict] = []
    marked: dict[int, str] = {}  # id(mesh) -> mesh with marker
    for binding in profile.shapekey_bindings:
        for mesh in meshes:
            key_blocks = _shape_keys_of(mesh)
            if key_blocks is None or binding.target not in key_blocks:
                continue
            key_block = key_blocks[binding.target]
            _remove_key_driver(key_block)
            entries.append({"key_block": key_block, "channel": binding.channel,
                            "gain": binding.gain, "invert": binding.invert})
            driven = list(mesh.get(DRIVEN_PROP, []))
            if binding.target not in driven:
                driven.append(binding.target)
            mesh[DRIVEN_PROP] = driven
            marked[id(mesh)] = mesh
    if profile.shapekey_bindings and not entries:
        raise BindingError(
            "No shape key binding could be created: check mesh selection")
    return entries


def _remove_key_driver(key_block) -> None:  # noqa: ANN001
    try:
        key_block.driver_remove("value")
    except RuntimeError:
        pass  # no existing driver


def _shape_keys_of(mesh):  # noqa: ANN001
    return getattr(mesh.data, "shape_keys", None) and mesh.data.shape_keys.key_blocks


def _bind_bones(profile: RigProfile, armature, empty_by_role: dict[str, str]) -> None:  # noqa: ANN001
    for binding in profile.bone_bindings:
        empty_name = empty_by_role.get(binding.point)
        if empty_name is None or binding.target not in armature.pose.bones:
            continue
        pose_bone = armature.pose.bones[binding.target]
        name = f"{CONSTRAINT_PREFIX}{binding.point}"
        old = pose_bone.constraints.get(name)
        if old:
            pose_bone.constraints.remove(old)
        constraint = pose_bone.constraints.new(_CONSTRAINT_TYPES[binding.constraint])
        constraint.name = name
        constraint.target = bpy.data.objects[empty_name]
        constraint.target_space = "LOCAL"
        constraint.owner_space = "LOCAL"
        if binding.constraint == "copy_location":
            constraint.use_x, constraint.use_y, constraint.use_z = binding.axes
            constraint.invert_x, constraint.invert_y, constraint.invert_z = binding.invert
            constraint.head_tail = binding.head_tail
        elif binding.constraint == "copy_rotation":
            constraint.use_x, constraint.use_y, constraint.use_z = binding.axes
            constraint.invert_x, constraint.invert_y, constraint.invert_z = binding.invert


_CONSTRAINT_TYPES = {
    "copy_location": "COPY_LOCATION",
    "copy_rotation": "COPY_ROTATION",
    "damped_track": "DAMPED_TRACK",
}


# -- removal -------------------------------------------------------------------

def unbind_all() -> None:
    """Remove every RealCapture binding marker from the scene. Idempotent."""
    # Shape key drivers (legacy cleanup): remove key-block drivers whose
    # variables read rc_shape_*
    for mesh in bpy.data.objects:
        if mesh.type != "MESH":
            continue
        key_blocks = getattr(mesh.data, "shape_keys", None)
        if not key_blocks:
            continue
        animation_data = key_blocks.animation_data
        if animation_data and animation_data.drivers:
            for fcurve in list(animation_data.drivers):
                data_path = fcurve.data_path
                if not data_path.startswith("key_blocks["):
                    continue
                reads_capture = any(
                    "rc_shape_" in (target.data_path or "")
                    for var in fcurve.driver.variables
                    for target in var.targets)
                if reads_capture:
                    try:
                        animation_data.driver_remove(data_path)
                    except RuntimeError:
                        pass
        if mesh.get(DRIVEN_PROP):
            # Assign instead of pop: idprop removal inside an operator context
            # can silently miss (Blender 4.x); an empty list means unbound.
            mesh[DRIVEN_PROP] = []
    # Bone constraints
    for armature_obj in bpy.data.objects:
        if armature_obj.type != "ARMATURE":
            continue
        for pose_bone in armature_obj.pose.bones:
            for constraint in [c for c in pose_bone.constraints
                               if c.name.startswith(CONSTRAINT_PREFIX)]:
                pose_bone.constraints.remove(constraint)
    # Empties + collection
    collection = bpy.data.collections.get(POINTS_COLLECTION)
    if collection:
        for obj in [o for o in collection.objects]:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)

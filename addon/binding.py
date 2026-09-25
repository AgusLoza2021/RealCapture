"""Blender binding layer: turns a RigProfile into native Blender links.

Everything here touches bpy and must run on the main thread (timer callbacks
or operators). The links we create are plain Blender data — drivers on shape
keys, constraints on bones, empties in a collection — so artists can inspect,
tweak or delete them without the addon. Unbind sweeps by our markers.

Naming/markers:
- FPD empties live in collection "RealCapture Points", named RC_pt_<role>.
- Bone constraints are named "RC_follow_<role>".
- Driven shape keys get custom prop "rc_driven_channel".
"""

from __future__ import annotations

import bpy

from .rigprofile.profile import BoneBinding, RigProfile

POINTS_COLLECTION = "RealCapture Points"
EMPTY_PREFIX = "RC_pt_"
CONSTRAINT_PREFIX = "RC_follow_"
DRIVEN_PROP = "rc_driven_channel"

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


class BindingError(RuntimeError):
    """Raised when a profile cannot be applied to the current scene."""


class FacePointRig:
    """Runtime handle over the FPD empties; called by the consumer each tick.

    Holds (role, kind, axis) -> (empty, rest_value, gain, invert). Transform
    entries accumulate per empty; the write is rest + sum(deltas), epsilon-
    gated to avoid depsgraph churn.
    """

    def __init__(self, entries: dict[str, list[dict]]) -> None:
        # entries[empty_name] = list of {kind, axis, gain, invert}
        self._entries = entries

    @property
    def empty_names(self) -> list[str]:
        return list(self._entries)

    def apply(self, packet) -> None:  # noqa: ANN001 - schema.Packet
        values = packet.shapes
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
    """Apply a full profile to the scene. Returns the runtime face-point rig."""
    unbind_all()

    empty_by_role = _create_empties(profile, armature)
    _bind_shapekeys(profile, controller, meshes)
    _bind_bones(profile, armature, empty_by_role)

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
    return FacePointRig({k: v for k, v in entries.items() if v})


# -- creation ----------------------------------------------------------------

def _create_empties(profile: RigProfile, armature) -> dict[str, str]:  # noqa: ANN001
    """Create the FPD empties, parented to the head bone. Returns role->empty name."""
    if armature is None:
        raise BindingError("No armature: face points need a head to attach to")
    head_bone = profile.head_bone or _guess_head_bone(armature)
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


def _guess_head_bone(armature) -> str | None:  # noqa: ANN001
    for pattern in ("head", "HEAD", "Head"):
        for bone in armature.data.bones:
            if bone.name.lower().startswith(pattern.lower()):
                return bone.name
    return None


def _bind_shapekeys(profile: RigProfile, controller, meshes) -> None:  # noqa: ANN001
    """Create drivers: shape key value <- controller rc_shape_<channel> prop.

    Uses a GENERATOR f-curve modifier (y = b + a*x) instead of a scripted
    expression, so bindings work without 'Auto Run Python Scripts'.
    """
    bound = 0
    for binding in profile.shapekey_bindings:
        prop = f'rc_shape_{binding.channel}'
        for mesh in meshes:
            key_blocks = _shape_keys_of(mesh)
            if key_blocks is None or binding.target not in key_blocks:
                continue
            key_block = key_blocks[binding.target]
            key_block[DRIVEN_PROP] = binding.channel
            _remove_key_driver(key_block)
            fcurve = key_block.driver_add("value")
            var = fcurve.driver.variables.new()
            var.name = "var"
            var.type = "SINGLE_PROP"
            var.targets[0].id = controller
            var.targets[0].data_path = f'["{prop}"]'
            generator = fcurve.modifiers.new(type="GENERATOR")
            if binding.invert:
                generator.coefficients = (binding.gain, -binding.gain)
            else:
                generator.coefficients = (0.0, binding.gain)
            bound += 1
    if profile.shapekey_bindings and bound == 0:
        raise BindingError("No shape key binding could be created: check mesh selection")


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
    # Shape key drivers
    for mesh in bpy.data.meshes:
        key_blocks = getattr(mesh, "shape_keys", None)
        if not key_blocks:
            continue
        for key_block in key_blocks.key_blocks:
            if key_block.get(DRIVEN_PROP) is not None:
                try:
                    key_block.driver_remove("value")
                except RuntimeError:
                    pass
                del key_block[DRIVEN_PROP]
    # Bone constraints
    for armature in bpy.data.armatures:
        for pose_bone in armature.pose_bones:
            for constraint in [c for c in pose_bone.constraints
                               if c.name.startswith(CONSTRAINT_PREFIX)]:
                pose_bone.constraints.remove(constraint)
    # Empties + collection
    collection = bpy.data.collections.get(POINTS_COLLECTION)
    if collection:
        for obj in [o for o in collection.objects]:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)

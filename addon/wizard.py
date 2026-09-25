"""Setup wizard operators: scan -> review -> bind -> save/load -> unbind.

Implements the workflow validated by the research pass
(docs/research/rig-mapping-workflow-landscape.md): auto-match against alias
lists, a review table the artist can edit, native bindings, reversible Unbind.
All bpy work happens inside operator execute (main thread).
"""

from __future__ import annotations

import bpy

from . import binding
from .rigprofile import build as profile_build
from .rigprofile import match_bones, match_shapekeys
from .rigprofile.channels import ARKIT_CHANNELS
from .rigprofile.profile import ProfileError, RigProfile


def _settings(context) -> bpy.types.PropertyGroup:  # noqa: ANN201
    return context.scene.realcapture


def _collect_shape_key_names(context) -> list[str]:  # noqa: ANN201
    settings = _settings(context)
    mesh = settings.rig_face_mesh
    if mesh is not None and mesh.data.shape_keys:
        return [k.name for k in mesh.data.shape_keys.key_blocks
                if k.name != "Basis"]
    # Fall back: every mesh with shape keys in the scene.
    names: list[str] = []
    for obj in context.scene.objects:
        if obj.type == "MESH" and obj.data.shape_keys:
            names.extend(k.name for k in obj.data.shape_keys.key_blocks
                         if k.name != "Basis")
    return names


def _collect_bone_names(context) -> list[str]:  # noqa: ANN201
    settings = _settings(context)
    armature = settings.rig_armature
    if armature is not None:
        return [b.name for b in armature.data.bones]
    return []


class REALCAPTURE_OT_scan_rig(bpy.types.Operator):
    """Scan the rig and auto-match shape keys and bones to capture channels"""

    bl_idname = "realcapture.scan_rig"
    bl_label = "Scan & Auto-Match Rig"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        shape_names = _collect_shape_key_names(context)
        bone_names = _collect_bone_names(context)
        if not shape_names and not bone_names:
            self.report({"WARNING"}, "No shape keys or bones found: assign Face Mesh / Armature")
            return {"CANCELLED"}

        shape_props = match_shapekeys(shape_names)
        bone_props = match_bones(bone_names)

        settings.rig_proposals.clear()
        for proposal in shape_props + bone_props:
            item = settings.rig_proposals.add()
            item.key = proposal.key
            item.kind = proposal.kind
            item.target = proposal.target
            item.confidence = proposal.confidence
            item.include = True

        self.report({"INFO"},
                    f"Matched {len(shape_props)} shape keys, {len(bone_props)} bones. "
                    "Review the table, then Build & Bind.")
        return {"FINISHED"}


class REALCAPTURE_OT_bind_rig(bpy.types.Operator):
    """Build a rig profile from the reviewed proposals and bind it to the scene"""

    bl_idname = "realcapture.bind_rig"
    bl_label = "Build & Bind"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        armature = settings.rig_armature
        if armature is None:
            self.report({"ERROR"}, "Assign the armature first")
            return {"CANCELLED"}

        included = [item for item in settings.rig_proposals if item.include]
        shape_props = profile_build.as_matcher_proposals(
            [item for item in included if item.kind == "shapekey"])
        bone_props = profile_build.as_matcher_proposals(
            [item for item in included if item.kind == "bone"])

        profile = profile_build.build_profile(
            name=bpy.path.basename(bpy.data.filepath) or "Scene rig",
            shapekey_proposals=shape_props,
            bone_proposals=bone_props,
            channel_catalog=set(ARKIT_CHANNELS),
            head_bone=settings.rig_head_bone or None,
            rig_kind="custom",
        )
        settings.rig_profile_path = settings.rig_profile_path or "//realcapture_rig_profile.json"
        profile.save(bpy.path.abspath(settings.rig_profile_path))

        controller = _get_controller(context)
        meshes = _collect_meshes(context)
        try:
            face_points = binding.bind_profile(
                profile, controller, meshes, armature)
        except binding.BindingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        _store_face_points(context, face_points, profile)
        self.report({"INFO"},
                    f"Bound: {len(profile.shapekey_bindings)} shape keys "
                    f"(consumer-driven), {len(profile.bone_bindings)} bones, "
                    f"{len(profile.points)} point transforms. "
                    f"Profile saved to {settings.rig_profile_path}")
        return {"FINISHED"}


class REALCAPTURE_OT_unbind_rig(bpy.types.Operator):
    """Remove every RealCapture binding (drivers, constraints, face points)"""

    bl_idname = "realcapture.unbind_rig"
    bl_label = "Unbind All"
    bl_options = {"REGISTER"}

    def execute(self, context):
        binding.unbind_all()
        _store_face_points(context, None, None)
        self.report({"INFO"}, "All RealCapture bindings removed")
        return {"FINISHED"}


class REALCAPTURE_OT_load_profile(bpy.types.Operator):
    """Load a saved rig profile and bind it"""

    bl_idname = "realcapture.load_profile"
    bl_label = "Load Profile & Bind"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        path = bpy.path.abspath(settings.rig_profile_path)
        armature = settings.rig_armature
        if armature is None:
            self.report({"ERROR"}, "Assign the armature first")
            return {"CANCELLED"}
        try:
            profile = RigProfile.load(path)
        except (OSError, ProfileError) as exc:
            self.report({"ERROR"}, f"Cannot load profile: {exc}")
            return {"CANCELLED"}

        controller = _get_controller(context)
        meshes = _collect_meshes(context)
        try:
            face_points = binding.bind_profile(profile, controller, meshes, armature)
        except binding.BindingError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        _store_face_points(context, face_points, profile)
        self.report({"INFO"}, f"Bound profile {profile.name!r} from {path}")
        return {"FINISHED"}


# -- helpers -------------------------------------------------------------------

def _get_controller(context):  # noqa: ANN201
    settings = _settings(context)
    if settings.controller is not None:
        return settings.controller
    # Fall back: reuse the auto-created controller empty if one exists.
    return bpy.data.objects.get("RealCapture_Controller")


def _collect_meshes(context) -> list:  # noqa: ANN201
    settings = _settings(context)
    if settings.rig_face_mesh is not None:
        return [settings.rig_face_mesh]
    return [obj for obj in context.scene.objects
            if obj.type == "MESH" and obj.data.shape_keys]


def _store_face_points(context, face_points, profile) -> None:  # noqa: ANN001
    """Attach the runtime rig to the active consumer and remember the profile."""
    from .ui import _get_consumer  # local import: avoids a ui<->wizard cycle

    consumer = _get_consumer()
    consumer.face_points = face_points
    context.scene["realcapture_bound_profile"] = (
        profile.to_dict() if profile is not None else None)


_CLASSES = (REALCAPTURE_OT_scan_rig, REALCAPTURE_OT_bind_rig,
            REALCAPTURE_OT_unbind_rig, REALCAPTURE_OT_load_profile)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

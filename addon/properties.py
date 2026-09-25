"""Scene-level addon settings."""

from __future__ import annotations

import bpy


class RealCaptureSettings(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(  # noqa: F841 - read by UI, operators
        name="Capture Running",
        description="True while the capture consumer timer is active",
        default=False,
    )
    udp_port: bpy.props.IntProperty(
        name="UDP Port",
        description="Local UDP port the addon listens on (must match the backend --port)",
        default=11111,
        min=1024,
        max=65535,
    )
    epsilon: bpy.props.FloatProperty(
        name="Epsilon",
        description="Skip property writes when a value changes less than this (0 disables gating)",
        default=0.002,
        min=0.0,
        max=0.1,
        precision=4,
    )
    controller: bpy.props.PointerProperty(  # noqa: F841
        name="Controller",
        description="Empty/object whose custom properties receive capture values (rc_shape_*, rc_pose_*)",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == "EMPTY",
    )
    record_session: bpy.props.BoolProperty(  # noqa: F841
        name="Record Session",
        description="Record incoming packets to session_path while capturing",
        default=False,
    )
    session_path: bpy.props.StringProperty(  # noqa: F841
        name="Session File",
        description="JSONL file for session recording (and the file replayed by Replay)",
        subtype="FILE_PATH",
        default="//realcapture_session.jsonl",
    )
    # -- Rig Connector (setup wizard) ----------------------------------------
    rig_profile_path: bpy.props.StringProperty(  # noqa: F841
        name="Rig Profile",
        description="JSON rig profile for the Universal Rig Connector",
        subtype="FILE_PATH",
        default="//realcapture_rig_profile.json",
    )
    rig_face_mesh: bpy.props.PointerProperty(  # noqa: F841
        name="Face Mesh",
        description="Mesh object whose shape keys receive the ARKit bindings",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == "MESH",
    )
    rig_armature: bpy.props.PointerProperty(  # noqa: F841
        name="Armature",
        description="Armature whose facial bones follow the face points",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == "ARMATURE",
    )
    rig_head_bone: bpy.props.StringProperty(  # noqa: F841
        name="Head Bone",
        description="Bone the face-point empties are parented to (blank = auto-detect)",
        default="",
    )
    rig_proposals: bpy.props.CollectionProperty(  # noqa: F841
        type=RigProposalItem,
    )


class RigProposalItem(bpy.types.PropertyGroup):
    """One auto-matched binding row in the wizard review table."""

    key: bpy.props.StringProperty(name="Channel/Role")
    kind: bpy.props.StringProperty(name="Kind")  # shapekey | bone
    target: bpy.props.StringProperty(name="Detected Control")
    confidence: bpy.props.FloatProperty(name="Confidence", precision=2)
    include: bpy.props.BoolProperty(name="Use", default=True)


def register() -> None:
    bpy.utils.register_class(RigProposalItem)
    bpy.utils.register_class(RealCaptureSettings)
    bpy.types.Scene.realcapture = bpy.props.PointerProperty(type=RealCaptureSettings)


def unregister() -> None:
    del bpy.types.Scene.realcapture
    bpy.utils.unregister_class(RealCaptureSettings)
    bpy.utils.unregister_class(RigProposalItem)

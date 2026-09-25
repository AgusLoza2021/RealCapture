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


def register() -> None:
    bpy.utils.register_class(RealCaptureSettings)
    bpy.types.Scene.realcapture = bpy.props.PointerProperty(type=RealCaptureSettings)


def unregister() -> None:
    del bpy.types.Scene.realcapture
    bpy.utils.unregister_class(RealCaptureSettings)

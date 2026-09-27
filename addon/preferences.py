"""RealCapture add-on preferences (needs bpy; imported lazily by register()).

Exactly the six frozen fields, nothing else in this module
(odd/tasks/blender-native-plugin.md, P4). ``bl_idname = __package__`` is the
correct idiom in both modes: dev ``addon`` and installed
``bl_ext.<repo>.realcapture``.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty


class RealCapturePreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    repo_root: StringProperty(  # noqa: F841 - read by the cockpit
        name="Repository folder",
        description="Root of the RealCapture repository (must contain backend/run_capture.py)",
        subtype="DIR_PATH",
        default="",
    )
    python_executable: StringProperty(  # noqa: F841 - read by the cockpit
        name="Backend interpreter",
        description=(
            "Python interpreter of the backend virtual environment; empty "
            "derives <repo_root>/backend/.venv/Scripts/python.exe"
        ),
        default="",
    )
    udp_port: IntProperty(  # noqa: F841 - read by the cockpit
        name="UDP port",
        description="Port the backend sends capture packets to (must match the scene's UDP port)",
        default=11111,
        min=1,
        max=65535,
    )
    dashboard_port: IntProperty(  # noqa: F841 - read by the cockpit
        name="Dashboard port",
        description="Port of the backend's Control Room dashboard",
        default=8765,
        min=1,
        max=65535,
    )
    camera_index: IntProperty(  # noqa: F841 - read by the cockpit
        name="Camera index",
        description="Zero-based OpenCV camera index the backend opens",
        default=0,
        min=0,
    )
    open_browser_on_start: BoolProperty(  # noqa: F841 - read by the cockpit
        name="Open browser on start",
        description="Open the Control Room in the browser when the backend starts",
        default=False,
    )


    def draw(self, context) -> None:  # noqa: ANN001, ARG002 - bpy passes the context
        """Render every frozen field.

        A preferences class with no ``draw`` is invisible in Blender's
        Preferences, and ``repo_root`` is the one value the user must set
        before anything can start: without this the cockpit is only reachable
        from Python.
        """
        layout = self.layout
        layout.label(text="Pipeline")
        layout.prop(self, "repo_root")
        layout.prop(self, "python_executable")
        row = layout.row(align=True)
        row.prop(self, "udp_port")
        row.prop(self, "dashboard_port")
        row = layout.row(align=True)
        row.prop(self, "camera_index")
        row.prop(self, "open_browser_on_start")


def register() -> None:
    bpy.utils.register_class(RealCapturePreferences)


def unregister() -> None:
    bpy.utils.unregister_class(RealCapturePreferences)

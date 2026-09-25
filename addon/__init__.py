"""RealCapture — real-time facial capture consumer for Blender.

Runs alongside the RealCapture capture backend (external process). Receives
UDP/JSON packets, applies the newest values as custom properties on a
controller empty, and reports live telemetry. Bind shape keys / bones to the
controller properties with native drivers.

Requires Blender 4.2+.

Package layout notes:
- Pure modules (schema, receiver, telemetry) import WITHOUT bpy so they can be
  unit-tested under plain pytest.
- bpy-dependent modules (consumer, properties, ui) are loaded lazily inside
  register()/unregister(), which Blender always calls with bpy available.
"""

bl_info = {
    "name": "RealCapture",
    "author": "RealCapture project",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N) > RealCapture",
    "description": "Real-time facial capture consumer: UDP receiver + telemetry",
    "category": "Animation",
}


def register() -> None:
    from . import properties, ui  # lazy: these import bpy

    ui.register()
    properties.register()


def unregister() -> None:
    from . import properties, ui  # lazy: these import bpy

    ui.unregister()
    properties.unregister()

"""Blender UI: operators and panel. Only imported inside register() (needs bpy)."""

from __future__ import annotations

import bpy

from .consumer import CaptureConsumer
from .session import SessionError, SessionRecorder

_consumer: CaptureConsumer | None = None


def _get_consumer() -> CaptureConsumer:
    """Lazy singleton so addon import stays side-effect free."""
    global _consumer
    if _consumer is None:
        _consumer = CaptureConsumer(get_controller=_get_controller)
    return _consumer


def _get_controller():
    context = bpy.context
    settings = getattr(context.scene, "realcapture", None)
    if settings is None or settings.controller is None:
        return None
    return settings.controller


def _start_recorder(settings) -> None:  # noqa: ANN001
    """Create and start a session recorder if record_session is enabled."""
    _stop_recorder()
    if not settings.record_session:
        return
    path = bpy.path.abspath(settings.session_path) or "realcapture_session.jsonl"
    recorder = SessionRecorder(path)
    recorder.start()
    _get_consumer().recorder = recorder


def _stop_recorder() -> None:
    consumer = _get_consumer()
    if consumer.recorder is not None:
        if consumer.recorder.is_recording:
            consumer.recorder.stop()
        consumer.recorder = None


class RC_OT_start_capture(bpy.types.Operator):
    """Start receiving facial capture data from the backend"""

    bl_idname = "realcapture.start_capture"
    bl_label = "Start Capture"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.realcapture
        if settings.controller is None:
            self.report({"WARNING"}, "Select a controller empty first")
            return {"CANCELLED"}
        consumer = _get_consumer()
        try:
            consumer.start(port=settings.udp_port)
        except OSError as exc:
            self.report({"ERROR"}, f"Cannot bind UDP port {settings.udp_port}: {exc}")
            return {"CANCELLED"}
        _start_recorder(settings)
        settings.enabled = True
        recorder_note = " (recording)" if consumer.recorder is not None else ""
        self.report({"INFO"}, f"Listening on UDP port {settings.udp_port}{recorder_note}")
        return {"FINISHED"}


class RC_OT_stop_capture(bpy.types.Operator):
    """Stop receiving facial capture data"""

    bl_idname = "realcapture.stop_capture"
    bl_label = "Stop Capture"
    bl_options = {"REGISTER"}

    def execute(self, context):
        consumer = _get_consumer()
        if consumer.running:
            consumer.stop()
        _stop_recorder()
        context.scene.realcapture.enabled = False
        return {"FINISHED"}


class RC_OT_replay_session(bpy.types.Operator):
    """Replay a recorded RealCapture session onto the controller"""

    bl_idname = "realcapture.replay_session"
    bl_label = "Replay Session"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.realcapture
        if settings.controller is None:
            self.report({"WARNING"}, "Select a controller empty first")
            return {"CANCELLED"}
        path = bpy.path.abspath(settings.session_path)
        consumer = _get_consumer()
        try:
            skipped = consumer.start_replay(path)
        except SessionError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        note = f" ({skipped} malformed lines skipped)" if skipped else ""
        self.report({"INFO"}, f"Replaying {path}{note}")
        return {"FINISHED"}


class RC_PT_main_panel(bpy.types.Panel):
    bl_label = "RealCapture"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RealCapture"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.realcapture
        consumer = _get_consumer()

        col = layout.column()
        col.prop(settings, "controller")
        col.prop(settings, "udp_port")
        col.prop(settings, "epsilon")

        row = col.row(align=True)
        row.operator("realcapture.start_capture", icon="PLAY", text="Start")
        row.operator("realcapture.stop_capture", icon="PAUSE", text="Stop")

        box = layout.box()
        box.label(text=f"Status: {'running' if consumer.running else 'stopped'}")
        if consumer.replaying:
            box.label(text="Mode: session replay")
        stats = consumer.stats
        box.label(text=f"Engine: {stats.engine or '-'}")
        box.label(text=f"Applied FPS: {stats.applied_fps:.1f}")
        box.label(text=f"Packets: {stats.packets_applied}")
        box.label(text=f"Transport: avg {stats.avg_transport_ms:.1f} ms / max {stats.max_transport_ms:.1f} ms")
        if stats.invalid_packets:
            box.label(text=f"Invalid packets: {stats.invalid_packets}", icon="ERROR")

        col = layout.column(align=True)
        col.prop(settings, "record_session")
        col.prop(settings, "session_path")
        col.operator("realcapture.replay_session", icon="FILE_REFRESH", text="Replay Session")

        col = layout.column(align=True)
        col.label(text="Bind drivers to:")
        col.label(text='  controller["rc_shape_<name>"]')
        col.label(text='  controller["rc_pose_<rx..tz>"]')


classes = (
    RC_OT_start_capture,
    RC_OT_stop_capture,
    RC_OT_replay_session,
    RC_PT_main_panel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    if _consumer is not None and _consumer.running:
        _consumer.stop()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

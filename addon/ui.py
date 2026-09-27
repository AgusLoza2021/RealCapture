"""Blender UI: operators and panel. Only imported inside register() (needs bpy)."""

from __future__ import annotations

import time

import bpy

from . import backend_process, cockpit, dashboard_client
from .cockpit import CockpitError
from .consumer import CaptureConsumer
from .session import SessionError, SessionRecorder

_consumer: CaptureConsumer | None = None
_process: backend_process.BackendProcess | None = None
_poller: dashboard_client.DashboardPoller | None = None
_poller_port: int | None = None


def _preferences_of(context):
    """This addon's preferences, or None when they are not available.

    For an installed extension the addons key is the FULL module path
    (``bl_ext.<repo>.realcapture``), which is exactly what ``__package__`` is
    inside this module in both modes. The panel must draw a sane section when
    ``.preferences`` is None instead of raising.
    """
    addons = context.preferences.addons
    entry = addons.get(__package__)
    if entry is None:
        return None
    return entry.preferences


def _ensure_poller(dashboard_port: int) -> None:
    """Start the dashboard poller for THIS port; its fetch runs off the UI thread.

    A poller already reading a different port is rebuilt, never reused: a
    panel whose port changed but whose data comes from the old one is stale
    by construction.
    """
    global _poller, _poller_port
    if not cockpit.needs_new_poller(_poller_port, dashboard_port):
        return
    _drop_poller()
    _poller = dashboard_client.DashboardPoller(dashboard_port)
    _poller.start()
    _poller_port = dashboard_port


def _drop_poller() -> None:
    global _poller, _poller_port
    if _poller is not None:
        _poller.stop()
        _poller = None
    _poller_port = None


def _ensure_timer() -> None:
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=cockpit.TICK_INTERVAL_S)


def _tick():
    """Timer callback: refresh the panel and return the next interval.

    Blender silently unregisters a timer that raises, which would freeze the
    panel's lights, so the whole body is guarded: on any failure the tick
    keeps itself alive with the ordinary interval.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        poller_alive = _poller is not None and _poller.is_alive()
        return cockpit.next_tick_interval(poller_alive)
    except Exception:  # noqa: BLE001 - a raising timer must never kill the redraw loop
        return cockpit.TICK_INTERVAL_S


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


class RC_OT_start_backend(bpy.types.Operator):
    """Start the capture backend as a hidden child process"""

    bl_idname = "realcapture.start_backend"
    bl_label = "Start Pipeline"
    bl_options = {"REGISTER"}

    def execute(self, context):
        global _process
        if _process is not None and _process.is_alive():
            self.report({"INFO"}, f"already running (pid {_process.pid})")
            return {"FINISHED"}
        prefs = _preferences_of(context)
        scene = getattr(context.scene, "realcapture", None)
        scene_udp_port = getattr(scene, "udp_port", None)
        try:
            settings = cockpit.settings_from_preferences(
                prefs, scene_udp_port=scene_udp_port
            )
            paths = settings.paths()
            argv = settings.argv()
        except (CockpitError, backend_process.BackendError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        process = backend_process.start_backend(
            paths, argv, prober=dashboard_client.probe_dashboard
        )
        _process = process
        _ensure_poller(settings.dashboard_port)
        _ensure_timer()
        if process.started:
            self.report({"INFO"}, process.reason)
        else:
            # Not started (port already held, probe failure): say exactly why.
            self.report({"WARNING"}, process.reason)
        return {"FINISHED"}


class RC_OT_stop_backend(bpy.types.Operator):
    """Stop the backend child this add-on started"""

    bl_idname = "realcapture.stop_backend"
    bl_label = "Stop Pipeline"
    bl_options = {"REGISTER"}

    def execute(self, context):
        global _process
        process = _process
        if process is None:
            self.report({"WARNING"}, "the backend was not started by this add-on")
            return {"CANCELLED"}
        result = process.stop()
        if cockpit.stop_clears_state(result):
            # Only a real stop forgets the child; a failed stop keeps it on the
            # panel, alive and named.
            _process = None
            _drop_poller()
        if result.stopped:
            self.report({"INFO"}, result.reason)
            return {"FINISHED"}
        # A stop that did not stop says so.
        self.report({"ERROR"}, result.reason)
        return {"CANCELLED"}


class RC_OT_open_control_room(bpy.types.Operator):
    """Open the RealCapture Control Room dashboard in the browser"""

    bl_idname = "realcapture.open_control_room"
    bl_label = "Open Control Room"
    bl_options = {"REGISTER"}

    def execute(self, context):
        prefs = _preferences_of(context)
        port = getattr(prefs, "dashboard_port", None)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            self.report(
                {"ERROR"},
                "the RealCapture preference 'dashboard_port' is not set to a usable port",
            )
            return {"CANCELLED"}
        bpy.ops.wm.url_open(url=f"http://127.0.0.1:{port}/")
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
        if stats.packets_dropped_stale:
            box.label(text=f"Stale drops: {stats.packets_dropped_stale}", icon="ERROR")

        self._draw_pipeline(layout, context)

        col = layout.column(align=True)
        col.prop(settings, "record_session")
        col.prop(settings, "session_path")
        col.operator("realcapture.replay_session", icon="FILE_REFRESH", text="Replay Session")

        col = layout.column(align=True)
        col.label(text="Bind drivers to:")
        col.label(text='  controller["rc_shape_<name>"]')
        col.label(text='  controller["rc_pose_<rx..tz>"]')


    def _draw_pipeline(self, layout, context) -> None:  # noqa: ANN001
        """The Pipeline box: start / stop / Control Room plus the lights."""
        box = layout.box()
        box.label(text="Pipeline")
        row = box.row(align=True)
        row.operator("realcapture.start_backend", icon="PLAY", text="Start")
        row.operator("realcapture.stop_backend", icon="PAUSE", text="Stop")
        box.operator(
            "realcapture.open_control_room", icon="WINDOW", text="Control Room"
        )

        prefs = _preferences_of(context)
        if prefs is None:
            box.label(
                text="RealCapture preferences are not available in this context",
                icon=cockpit.light_icon("unknown"),
            )
        else:
            for health in cockpit.child_rows(_process):
                self._draw_health_row(box, health)
            if _poller is not None:
                snapshot = _poller.snapshot()  # cached read: no I/O on this thread
                for health in cockpit.connection_rows(snapshot, now_s=time.monotonic()):
                    self._draw_health_row(box, health)
            else:
                box.label(
                    text="Dashboard: not polling (start the pipeline)",
                    icon=cockpit.light_icon("unknown"),
                )

    @staticmethod
    def _draw_health_row(layout, health) -> None:  # noqa: ANN001
        """One HealthRow: state as text as well as icon, detail on its own line."""
        row = layout.row(align=True)
        row.label(text=f"{health.label}: {health.state}", icon=health.icon)
        if health.detail:
            row.label(text=health.detail)


class RC_PT_rig_connector_panel(bpy.types.Panel):
    bl_label = "Rig Connector"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "RealCapture"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.realcapture

        col = layout.column()
        col.prop(settings, "rig_face_mesh")
        col.prop(settings, "rig_armature")
        col.prop(settings, "rig_head_bone")

        row = col.row(align=True)
        row.operator("realcapture.scan_rig", icon="VIEWZOOM", text="Scan & Auto-Match")

        if len(settings.rig_proposals):
            box = layout.box()
            box.label(text=f"Review bindings ({len(settings.rig_proposals)}):",
                      icon="CHECKLIST")
            for item in settings.rig_proposals:
                row = box.row(align=True)
                row.prop(item, "include", text="")
                sub = row.row()
                sub.alignment = "LEFT"
                sub.enabled = False  # read-only review row
                sub.label(text=f"{item.key} -> {item.target}")
                right = row.row()
                right.alignment = "RIGHT"
                right.enabled = False
                right.label(text=f"{item.confidence:.2f}")

        row = layout.row(align=True)
        row.operator("realcapture.bind_rig", icon="LINKED", text="Build & Bind")
        row.operator("realcapture.unbind_rig", icon="UNLINKED", text="Unbind")

        col = layout.column(align=True)
        col.prop(settings, "rig_profile_path")
        col.operator("realcapture.load_profile", icon="FILE_TICK", text="Load Profile & Bind")


classes = (
    RC_OT_start_capture,
    RC_OT_stop_capture,
    RC_OT_replay_session,
    RC_OT_start_backend,
    RC_OT_stop_backend,
    RC_OT_open_control_room,
    RC_PT_main_panel,
    RC_PT_rig_connector_panel,
)


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    _ensure_timer()


def unregister() -> None:
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _drop_poller()
    global _process
    process = _process
    _process = None
    if process is not None:
        # Rule 11: disabling the addon must not leave a camera running.
        process.stop()
    if _consumer is not None and _consumer.running:
        _consumer.stop()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

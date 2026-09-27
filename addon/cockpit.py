"""Pure cockpit model for the Blender-native plugin: the decisions the panel
draws, with no bpy import so it runs under pytest on a plain Python.

No bpy imports here on purpose; this module may only depend on the standard
library plus the two pure launcher/reader units (``backend_process`` and
``dashboard_client``). ``addon/ui.py`` only draws what this module decides.

Frozen interface (odd/tasks/blender-native-plugin.md, P4):

- ``settings_from_preferences`` reads the six preference fields; a missing
  attribute refuses naming that attribute, an empty ``repo_root`` refuses
  naming the field, and a scene UDP port that disagrees with the preference
  refuses naming BOTH values (never pick one silently).
- The lights are the dashboard's, verbatim: ``connection_rows`` renders the
  dashboard's own ``connections`` array (label and reason) and only adds the
  age of the snapshot. Absence is never green.
- ``child_rows`` reports the child this add-on started, with its reason
  verbatim, so ``it exited immediately (exit code 3); see the log: <path>``
  reaches the user instead of a green-looking panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple, Optional

from . import backend_process, dashboard_client
from .backend_process import BackendProcess, BackendPaths
from .dashboard_client import Snapshot

DEFAULT_PYTHON_RELATIVE = "backend/.venv/Scripts/python.exe"
DEFAULT_SCRIPT_RELATIVE = "backend/run_capture.py"
DEFAULT_UDP_PORT = 11111
DEFAULT_DASHBOARD_PORT = 8765
DEFAULT_CAMERA_INDEX = 0

#: Seconds between panel refreshes while the dashboard poller is alive.
TICK_INTERVAL_S = 0.5

#: The six preference fields the cockpit reads; all are required.
_PREFERENCE_FIELDS = (
    "repo_root",
    "python_executable",
    "udp_port",
    "dashboard_port",
    "camera_index",
    "open_browser_on_start",
)

#: The dashboard's own per-connection states (backend/dashboard/status_model.py).
_DASHBOARD_STATES = ("green", "yellow", "red")

_STATES = _DASHBOARD_STATES + ("unknown",)


class CockpitError(ValueError):
    """Every cockpit refusal raises this; the message names the offending thing."""


@dataclass(frozen=True)
class PipelineSettings:
    """The launch configuration read from the add-on preferences."""

    repo_root: str
    python_executable: str = ""  # empty means "derive it from repo_root"
    udp_port: int = DEFAULT_UDP_PORT
    dashboard_port: int = DEFAULT_DASHBOARD_PORT
    camera_index: int = DEFAULT_CAMERA_INDEX
    open_browser_on_start: bool = False

    def paths(self) -> BackendPaths:
        """Resolve the four launcher paths; delegates to ``backend_process``."""
        return backend_process.resolve_paths(
            self.repo_root,
            python_executable=self.python_executable or None,
        )

    def argv(self) -> list[str]:
        """Build the exact child argv; delegates to ``backend_process`` so the
        panel never assembles a command line itself."""
        return backend_process.build_argv(
            self.paths(),
            camera=self.camera_index,
            udp_port=self.udp_port,
            dashboard_port=self.dashboard_port,
        )


def settings_from_preferences(
    prefs: Any, *, scene_udp_port: Optional[int] = None
) -> PipelineSettings:
    """Read the six preference fields into a :class:`PipelineSettings`.

    A missing attribute is a :class:`CockpitError` naming the attribute, never
    a silent default. An empty ``repo_root`` refuses naming the preference
    field. When ``scene_udp_port`` is given and differs from the preference,
    the refusal names BOTH values: the addon's UDP consumer and the backend
    must agree, and the addon never picks one silently.
    """
    for name in _PREFERENCE_FIELDS:
        if not hasattr(prefs, name):
            raise CockpitError(
                f"the RealCapture preferences are missing the field {name!r}"
            )
    repo_root = prefs.repo_root
    if not isinstance(repo_root, str) or not repo_root.strip():
        raise CockpitError(
            "the RealCapture preference 'repo_root' is empty: set the RealCapture "
            "repository folder in the add-on preferences"
        )
    pref_udp_port = prefs.udp_port
    if scene_udp_port is not None and scene_udp_port != pref_udp_port:
        raise CockpitError(
            "UDP port disagreement: the scene uses udp_port="
            f"{scene_udp_port!r} but the add-on preference uses udp_port="
            f"{pref_udp_port!r}; they must agree before the backend starts"
        )
    return PipelineSettings(
        repo_root=repo_root,
        python_executable=str(prefs.python_executable or ""),
        udp_port=pref_udp_port,
        dashboard_port=prefs.dashboard_port,
        camera_index=prefs.camera_index,
        open_browser_on_start=bool(prefs.open_browser_on_start),
    )


class HealthRow(NamedTuple):
    """One light the panel renders: state, label, reason, and its icon."""

    state: str
    label: str
    detail: str
    icon: str


_LIGHT_ICONS = {
    "green": "CHECKMARK",
    "yellow": "QUESTION",
    "red": "ERROR",
    "unknown": "QUESTION",
}


def light_icon(state: str) -> str:
    """The Blender icon name for a cockpit state; anything else is a question."""
    return _LIGHT_ICONS.get(state, "QUESTION")


def child_rows(process: Optional[BackendProcess]) -> tuple[HealthRow, ...]:
    """One row for the backend child this add-on started, or a not-started row.

    The process ``reason`` is rendered verbatim, so a child that died inside
    the startup grace shows its exit code and log path. Green only while the
    child is actually alive.
    """
    if process is None:
        return (
            HealthRow(
                state="unknown",
                label="Backend",
                detail="not started",
                icon=light_icon("unknown"),
            ),
        )
    state = "green" if process.is_alive() else "red"
    return (
        HealthRow(
            state=state,
            label="Backend",
            detail=process.reason,
            icon=light_icon(state),
        ),
    )


def _age_suffix(snapshot: Snapshot, *, now_s: float) -> str:
    """``snapshot age <human>`` for a snapshot that had at least one good read.

    ``fetched_at == 0.0`` means no successful read yet and must never be
    rendered as an age (P3 contract).
    """
    if snapshot.fetched_at <= 0.0:
        return ""
    age_s = max(0.0, now_s - snapshot.fetched_at)
    return f"snapshot age {dashboard_client.format_age(age_s)}"


def connection_rows(snapshot: Snapshot, *, now_s: float) -> tuple[HealthRow, ...]:
    """The dashboard's own ``connections`` array, verbatim, one row each.

    ``label`` is the dashboard's ``label`` and ``detail`` is its ``reason``,
    with the snapshot's age appended. An empty array with an ``error`` renders
    ONE red row naming the error; an empty array with no error renders ONE
    unknown row. Absence is never green. The row state is the dashboard's own
    per-connection state; this module computes no threshold of its own. When
    the snapshot carries an ``error``, the rows are the LAST GOOD data still
    being shown, so a green row is downgraded to yellow: the reason and the
    age stay verbatim on the detail.
    """
    connections = snapshot.connections
    if not connections:
        if snapshot.error:
            return (
                HealthRow(
                    state="red",
                    label="Dashboard",
                    detail=snapshot.error,
                    icon=light_icon("red"),
                ),
            )
        return (
            HealthRow(
                state="unknown",
                label="Dashboard",
                detail="the dashboard reported no connections",
                icon=light_icon("unknown"),
            ),
        )
    rows: list[HealthRow] = []
    for conn in connections:
        if not isinstance(conn, dict):
            state, label, reason = "unknown", "?", ""
        else:
            raw_state = conn.get("state")
            state = raw_state if raw_state in _DASHBOARD_STATES else "unknown"
            if snapshot.error and state == "green":
                state = "yellow"  # last good data, not live
            label = str(conn.get("label", "?"))
            reason = str(conn.get("reason", ""))
        detail = reason
        suffix = _age_suffix(snapshot, now_s=now_s)
        if suffix:
            detail = f"{detail}; {suffix}" if detail else suffix
        rows.append(
            HealthRow(state=state, label=label, detail=detail, icon=light_icon(state))
        )
    return tuple(rows)


def stop_clears_state(result: Any) -> bool:
    """Whether a stop attempt lets the cockpit forget the child it started.

    Only a stop that ACTUALLY stopped clears the state. A failed stop must
    leave the child on the panel, alive and named, instead of reporting
    "not started" while a camera keeps running behind the user's back: the
    same defect family as a green light with nothing behind it.
    """
    return bool(getattr(result, "stopped", False))


def needs_new_poller(current_port: Optional[int], wanted_port: int) -> bool:
    """Whether the dashboard poller must be rebuilt for ``wanted_port``.

    A poller still reading the old port while the panel claims to show the new
    one is stale-by-construction; rebuild instead of reusing.
    """
    return current_port != wanted_port


def next_tick_interval(poller_alive: bool) -> Optional[float]:
    """The timer's own decision, pure and testable: ``None`` stops the timer."""
    if not poller_alive:
        return None
    return TICK_INTERVAL_S

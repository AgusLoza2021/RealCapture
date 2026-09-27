"""Unit tests for the pure cockpit model (no bpy anywhere).

Gates, not decoration: the refusals name the offending values (both ports on
disagreement, the field on an empty repo_root, the attribute on a missing
preference), the connection rows render the dashboard's array verbatim plus
the snapshot age, absence is never green, and the tick decision is pure.

The fake preference object is a plain object with the six attributes, NOT a
bpy type; the fake process is a plain object with is_alive() and reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from addon import backend_process, cockpit
from addon.cockpit import (
    CockpitError,
    HealthRow,
    PipelineSettings,
    connection_rows,
    child_rows,
    light_icon,
    next_tick_interval,
    settings_from_preferences,
)
from addon.dashboard_client import Snapshot


def _prefs(**overrides):
    """A plain preference object with the six frozen attributes."""
    values = dict(
        repo_root="C:/some/repo",
        python_executable="",
        udp_port=11111,
        dashboard_port=8765,
        camera_index=0,
        open_browser_on_start=False,
    )
    values.update(overrides)
    return type("FakePreferences", (), values)()


@dataclass
class FakeProcess:
    alive: bool
    reason: str = ""
    pid: Optional[int] = None

    def is_alive(self) -> bool:
        return self.alive


# ---------------------------------------------------------------------------
# constants


def test_defaults_match_the_frozen_values():
    assert cockpit.DEFAULT_PYTHON_RELATIVE == "backend/.venv/Scripts/python.exe"
    assert cockpit.DEFAULT_SCRIPT_RELATIVE == "backend/run_capture.py"
    assert cockpit.DEFAULT_UDP_PORT == 11111
    assert cockpit.DEFAULT_DASHBOARD_PORT == 8765
    assert cockpit.DEFAULT_CAMERA_INDEX == 0


# ---------------------------------------------------------------------------
# settings_from_preferences


def test_settings_from_preferences_reads_all_six_fields():
    settings = settings_from_preferences(
        _prefs(
            repo_root="D:/rc",
            python_executable="D:/rc/py.exe",
            udp_port=12345,
            dashboard_port=9999,
            camera_index=2,
            open_browser_on_start=True,
        )
    )
    assert settings == PipelineSettings(
        repo_root="D:/rc",
        python_executable="D:/rc/py.exe",
        udp_port=12345,
        dashboard_port=9999,
        camera_index=2,
        open_browser_on_start=True,
    )


def test_settings_scene_udp_port_agreeing_is_accepted():
    settings = settings_from_preferences(_prefs(), scene_udp_port=11111)
    assert settings.udp_port == 11111


def test_settings_refuse_disagreeing_scene_udp_port_naming_both_values():
    with pytest.raises(CockpitError) as excinfo:
        settings_from_preferences(_prefs(udp_port=11111), scene_udp_port=22222)
    message = str(excinfo.value)
    assert "11111" in message
    assert "22222" in message


def test_settings_refuse_empty_repo_root_naming_the_field():
    with pytest.raises(CockpitError) as excinfo:
        settings_from_preferences(_prefs(repo_root="   "))
    message = str(excinfo.value)
    assert "repo_root" in message


@pytest.mark.parametrize(
    "missing", ["repo_root", "python_executable", "udp_port", "dashboard_port", "camera_index", "open_browser_on_start"]
)
def test_settings_refuse_a_missing_preference_attribute_naming_it(missing):
    class Incomplete:
        pass

    for name, value in type(_prefs()).__dict__.items():
        if name.startswith("__") or name == missing:
            continue
        setattr(Incomplete, name, value)
    with pytest.raises(CockpitError) as excinfo:
        settings_from_preferences(Incomplete())
    assert missing in str(excinfo.value)


# ---------------------------------------------------------------------------
# PipelineSettings.paths()/argv() delegate to backend_process


def test_argv_delegates_to_backend_process_and_never_builds_a_command_line(monkeypatch):
    captured = {}

    def fake_resolve_paths(repo_root, *, python_executable=None, script=None, log_path=None):
        captured["repo_root"] = repo_root
        captured["python_executable"] = python_executable
        return backend_process.BackendPaths(
            repo_root=repo_root, python=python_executable, script="s", log_path="l"
        )

    monkeypatch.setattr(cockpit.backend_process, "resolve_paths", fake_resolve_paths)
    settings = PipelineSettings(
        repo_root="D:/rc", udp_port=12345, dashboard_port=9999, camera_index=2
    )
    argv = settings.argv()
    assert captured["repo_root"] == "D:/rc"
    assert captured["python_executable"] is None  # empty preference derives it
    assert "--port" in argv and "12345" in argv
    assert "--dashboard" in argv and "9999" in argv
    assert "--camera" in argv and "2" in argv


# ---------------------------------------------------------------------------
# light_icon


def test_light_icon_maps_the_frozen_icon_names():
    assert light_icon("green") == "CHECKMARK"
    assert light_icon("red") == "ERROR"
    assert light_icon("yellow") == "QUESTION"
    assert light_icon("unknown") == "QUESTION"
    assert light_icon("nonsense") == "QUESTION"  # never a crash, never green


# ---------------------------------------------------------------------------
# child_rows


def test_child_rows_without_a_process_is_one_unknown_not_started_row():
    (row,) = child_rows(None)
    assert isinstance(row, HealthRow)
    assert row.state == "unknown"
    assert row.label == "Backend"
    assert "not started" in row.detail
    assert row.icon == light_icon("unknown")


def test_child_rows_live_process_is_green_with_the_reason_verbatim():
    reason = "backend started (pid 4242); dashboard port 8765 was checked"
    (row,) = child_rows(FakeProcess(alive=True, reason=reason))
    assert row.state == "green"
    assert row.label == "Backend"
    assert row.detail == reason


def test_child_rows_dead_process_is_red_with_the_reason_verbatim():
    reason = "backend started (pid 7); dashboard port 8765 was not checked; it exited immediately (exit code 3); see the log: X"
    (row,) = child_rows(FakeProcess(alive=False, reason=reason))
    assert row.state == "red"
    assert row.detail == reason


# ---------------------------------------------------------------------------
# connection_rows


def _snapshot(connections=(), fetched_at=100.0, error=None):
    return Snapshot(connections=connections, fetched_at=fetched_at, error=error)


def test_connection_rows_render_the_dashboard_array_verbatim_with_age():
    conn = {"id": "cam", "label": "webcam", "state": "green", "reason": "camera ok", "detail": {}}
    rows = connection_rows(_snapshot(connections=[conn], fetched_at=100.0), now_s=112.0)
    assert len(rows) == 1
    row = rows[0]
    assert row.label == "webcam"
    assert row.state == "green"
    assert "camera ok" in row.detail
    assert "12 s" in row.detail  # the snapshot age, on every row


def test_connection_rows_keep_the_dashboard_state_not_their_own_threshold():
    yellow = {"label": "blender", "state": "yellow", "reason": "stale packets"}
    red = {"label": "consumer", "state": "red", "reason": "bind refused"}
    rows = connection_rows(
        _snapshot(connections=[yellow, red], fetched_at=50.0), now_s=51.0
    )
    assert [row.state for row in rows] == ["yellow", "red"]


def test_connection_rows_unknown_dashboard_state_is_never_green():
    conn = {"label": "weird", "state": "flashing purple", "reason": "unexpected"}
    (row,) = connection_rows(_snapshot(connections=[conn]), now_s=101.0)
    assert row.state == "unknown"


def test_connection_rows_never_render_fetched_at_zero_as_an_age():
    conn = {"label": "webcam", "state": "green", "reason": "camera ok"}
    (row,) = connection_rows(_snapshot(connections=[conn], fetched_at=0.0), now_s=99.0)
    assert "age" not in row.detail


def test_connection_rows_empty_array_with_error_is_one_red_row_naming_the_error():
    rows = connection_rows(_snapshot(error="connection refused"), now_s=100.0)
    assert len(rows) == 1
    row = rows[0]
    assert row.state == "red"
    assert "connection refused" in row.detail


def test_connection_rows_empty_array_without_error_is_one_unknown_row():
    rows = connection_rows(_snapshot(error=None), now_s=100.0)
    assert len(rows) == 1
    row = rows[0]
    assert row.state == "unknown"
    assert "no connections" in row.detail


def test_connection_rows_offline_is_never_green_even_with_stale_data():
    conn = {"label": "webcam", "state": "green", "reason": "camera ok"}
    rows = connection_rows(
        _snapshot(connections=[conn], fetched_at=95.0, error="timeout after 1.5 s"),
        now_s=100.0,
    )
    assert all(row.state != "green" for row in rows)
    assert "5.0 s" in rows[0].detail  # stale data is labelled with its age


# ---------------------------------------------------------------------------
# next_tick_interval


def test_next_tick_interval_stops_when_the_poller_is_not_alive():
    assert next_tick_interval(False) is None


def test_next_tick_interval_returns_a_positive_interval_while_alive():
    interval = next_tick_interval(True)
    assert isinstance(interval, float)
    assert interval > 0.0


# ---------------------------------------------------------------------------
# stop_clears_state / needs_new_poller


def test_stop_clears_state_only_after_a_real_stop():
    from addon.backend_process import StopResult

    assert cockpit.stop_clears_state(StopResult(True, "stopped (exit 0)", 0)) is True
    assert (
        cockpit.stop_clears_state(
            StopResult(False, "the process is still alive after 10.0 s", None)
        )
        is False
    )


def test_needs_new_poller():
    assert cockpit.needs_new_poller(None, 8765) is True
    assert cockpit.needs_new_poller(8765, 8765) is False
    assert cockpit.needs_new_poller(8765, 9000) is True

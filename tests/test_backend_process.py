"""Unit tests for the pure launcher core (no bpy, real temp trees).

Gates, not decoration: the argv builder round-trips through the REAL
``backend.run_capture.parse_args``, the path resolution proves there is no
PATH fallback, and a real child process proves the Popen contract (no shell,
repo cwd, DEVNULL stdin, hidden-window flags on Windows) plus an honest stop.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from addon.backend_process import (
    PROBE_DASHBOARD,
    PROBE_FREE,
    PROBE_STRANGER,
    BackendError,
    BackendProcess,
    ProbeResult,
    build_argv,
    build_environment,
    resolve_paths,
    start_backend,
)
from backend.run_capture import parse_args


def _make_repo(tmp_path: Path) -> Path:
    """A temporary real tree with an interpreter file and the real script."""
    repo = tmp_path / "repo"
    (repo / "backend" / ".venv" / "Scripts").mkdir(parents=True)
    (repo / "backend" / "run_capture.py").write_text("# script\n")
    (repo / "backend" / ".venv" / "Scripts" / "python.exe").write_text("# stub\n")
    return repo


def _paths(tmp_path: Path):
    return resolve_paths(_make_repo(tmp_path))


# ---------------------------------------------------------------------------
# resolve_paths


def test_resolve_paths_returns_absolute_defaults(tmp_path):
    repo = _make_repo(tmp_path)
    paths = resolve_paths(repo)
    assert paths.repo_root.is_absolute() and paths.repo_root == repo.resolve()
    assert paths.python == (repo / "backend" / ".venv" / "Scripts" / "python.exe").resolve()
    assert paths.script == (repo / "backend" / "run_capture.py").resolve()
    assert paths.log_path == (repo / "soak_output" / "backend.log").resolve()


def test_resolve_paths_overrides(tmp_path):
    repo = _make_repo(tmp_path)
    alt_py = tmp_path / "other-python.exe"
    alt_py.write_text("")
    alt_log = tmp_path / "logs" / "out.log"
    paths = resolve_paths(
        repo, python_executable=alt_py, log_path=alt_log
    )
    assert paths.python == alt_py.resolve()
    assert paths.log_path == alt_log.resolve()
    # The log's DIRECTORY may be missing (fresh clone): resolution must not fail.
    assert not alt_log.parent.exists()


def test_resolve_paths_missing_interpreter_names_venv_path_no_path_fallback(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "backend" / ".venv" / "Scripts" / "python.exe").unlink()
    with pytest.raises(BackendError) as excinfo:
        resolve_paths(repo)
    expected = str((repo / "backend" / ".venv" / "Scripts" / "python.exe").resolve())
    assert expected in str(excinfo.value)


def test_resolve_paths_missing_script_names_exact_path(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "backend" / "run_capture.py").unlink()
    with pytest.raises(BackendError) as excinfo:
        resolve_paths(repo)
    assert str((repo / "backend" / "run_capture.py").resolve()) in str(excinfo.value)


@pytest.mark.parametrize("bad_root", [None, "", "   "])
def test_resolve_paths_empty_repo_root_tells_user_to_set_preferences(tmp_path, bad_root):
    with pytest.raises(BackendError) as excinfo:
        resolve_paths(bad_root)
    assert "preferences" in str(excinfo.value)


def test_resolve_paths_nonexistent_repo_root(tmp_path):
    with pytest.raises(BackendError) as excinfo:
        resolve_paths(tmp_path / "no-such-repo")
    assert str((tmp_path / "no-such-repo").resolve()) in str(excinfo.value)


# ---------------------------------------------------------------------------
# build_environment


def test_build_environment_adds_only_pythonunbuffered():
    base = {"PATH": "x", "PYTHONUNBUFFERED": "0"}
    env = build_environment(base)
    assert env["PYTHONUNBUFFERED"] == "1"
    assert set(env) == set(base) | {"PYTHONUNBUFFERED"}
    assert "PATH" in env
    # The base environment is not mutated.
    assert base["PYTHONUNBUFFERED"] == "0"


# ---------------------------------------------------------------------------
# build_argv


def test_build_argv_round_trips_through_real_parser(tmp_path):
    paths = _paths(tmp_path)
    argv = build_argv(
        paths,
        engine="openseeface",
        camera=2,
        fps=24,
        host="192.168.1.5",
        udp_port=22222,
        dashboard_port=8123,
        stream_fps=7.5,
    )
    assert all(isinstance(item, str) for item in argv)
    assert argv[0] == str(paths.python)
    assert argv[1] == str(paths.script)
    flags = argv[2:]
    ns = parse_args(flags)
    assert ns.engine == "openseeface"
    assert ns.camera == 2
    assert ns.fps == 24
    assert ns.host == "192.168.1.5"
    assert ns.port == 22222
    assert ns.dashboard == 8123
    assert ns.stream_fps == pytest.approx(7.5)


def test_build_argv_omits_stream_fps_flag_when_none(tmp_path):
    paths = _paths(tmp_path)
    argv = build_argv(paths)
    assert "--stream-fps" not in argv
    ns = parse_args(argv[2:])
    assert ns.dashboard == 8765


def test_build_argv_does_not_clamp_stream_fps(tmp_path):
    paths = _paths(tmp_path)
    argv = build_argv(paths, stream_fps=99.0)
    ns = parse_args(argv[2:])
    assert ns.stream_fps == pytest.approx(99.0)


@pytest.mark.parametrize(
    "kwargs, offending",
    [
        ({"dashboard_port": 0}, "dashboard"),
        ({"udp_port": 0}, "udp_port"),
        ({"udp_port": 65536}, "udp_port"),
        ({"dashboard_port": -1}, "dashboard_port"),
        ({"engine": "faceware"}, "engine"),
        ({"fps": 0}, "fps"),
        ({"fps": -5}, "fps"),
        ({"camera": -1}, "camera"),
        ({"stream_fps": 0}, "stream_fps"),
        ({"stream_fps": -1.0}, "stream_fps"),
    ],
)
def test_build_argv_refusals(tmp_path, kwargs, offending):
    paths = _paths(tmp_path)
    with pytest.raises(BackendError) as excinfo:
        build_argv(paths, **kwargs)
    assert offending in str(excinfo.value)


def test_build_argv_refuses_dashboard_zero_because_lights_need_it(tmp_path):
    paths = _paths(tmp_path)
    with pytest.raises(BackendError) as excinfo:
        build_argv(paths, dashboard_port=0)
    message = str(excinfo.value)
    assert "lights" in message
    assert "dashboard" in message


# ---------------------------------------------------------------------------
# start_backend: probe refusals


def test_start_backend_refuses_on_dashboard_probe(tmp_path):
    paths = _paths(tmp_path)
    argv = build_argv(paths)
    process = start_backend(
        paths, argv, prober=lambda port: ProbeResult(PROBE_DASHBOARD, "already there")
    )
    assert process.started is False
    assert process.pid is None
    assert "already running" in process.reason
    assert "reused" in process.reason


def test_start_backend_refuses_on_stranger_probe(tmp_path):
    paths = _paths(tmp_path)
    argv = build_argv(paths, dashboard_port=9999)
    process = start_backend(
        paths, argv, prober=lambda port: ProbeResult(PROBE_STRANGER, "some web app")
    )
    assert process.started is False
    assert process.pid is None
    assert "9999" in process.reason
    assert "not this dashboard" in process.reason


def test_start_backend_refusal_when_prober_raises(tmp_path):
    paths = _paths(tmp_path)
    argv = build_argv(paths)

    def boom(port):
        raise OSError("probe socket blew up")

    process = start_backend(paths, argv, prober=boom)
    assert process.started is False
    assert process.pid is None
    assert "probe socket blew up" in process.reason


def test_start_backend_prober_receives_dashboard_port(tmp_path):
    paths = _paths(tmp_path)
    seen = []
    start_backend(
        paths,
        build_argv(paths, dashboard_port=8765),
        prober=lambda port: (seen.append(port), ProbeResult(PROBE_FREE))[1],
    )
    assert seen == [8765]


def test_start_backend_without_prober_says_port_was_not_checked(tmp_path):
    paths = _paths(tmp_path)

    class FakePopen:
        pid = 555

        def poll(self):
            return 0  # already exited: stop() is a no-op

    process = start_backend(
        paths, build_argv(paths), prober=None, popen_factory=lambda argv, **kw: FakePopen()
    )
    assert process.started is True
    assert process.pid == 555
    assert "not checked" in process.reason
    assert process.stop().stopped is True


# ---------------------------------------------------------------------------
# start_backend: real child process


def test_start_backend_real_child_contract_and_stop(tmp_path):
    paths = _paths(tmp_path)
    recorded: dict = {}

    def recorder(argv, **kwargs):
        recorded["argv"] = argv
        recorded["kwargs"] = kwargs
        return subprocess.Popen(argv, **kwargs)

    child_argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    process = None
    try:
        process = start_backend(
            paths,
            child_argv,
            prober=lambda port: ProbeResult(PROBE_FREE),
            popen_factory=recorder,
        )
        assert process.started is True
        assert process.pid is not None

        kwargs = recorded["kwargs"]
        assert kwargs.get("shell") is not True
        assert Path(kwargs["cwd"]) == paths.repo_root
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.STDOUT
        if sys.platform == "win32":
            flags = kwargs["creationflags"]
            assert flags & subprocess.CREATE_NO_WINDOW
            assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            assert kwargs["creationflags"] == 0

        assert process.is_alive() is True
        log_handle = process.log_handle
        result = process.stop(timeout_s=10.0)
        assert result.stopped is True
        assert process.is_alive() is False
        assert log_handle.closed is True
    finally:
        if process is not None and process.is_alive():
            process.stop(timeout_s=10.0)


def test_started_log_file_is_appended_in_log_directory(tmp_path):
    paths = _paths(tmp_path)
    assert not paths.log_path.parent.exists()  # fresh clone has no soak_output/
    process = None
    try:
        process = start_backend(paths, [sys.executable, "-c", "pass"], prober=None)
        assert paths.log_path.parent.exists()
    finally:
        if process is not None:
            process.stop(timeout_s=10.0)


# ---------------------------------------------------------------------------
# stop: honesty about children it did not start and children that refuse to die


class ImmortalFakePopen:
    """A fake child whose poll() never reports an exit."""

    def __init__(self) -> None:
        self.pid = 424242

    def poll(self):
        return None


def test_stop_fake_child_that_refuses_to_die_reports_the_wait():
    process = BackendProcess(ImmortalFakePopen())
    result = process.stop(timeout_s=0.3)
    assert result.stopped is False
    assert result.exit_code is None
    assert "0.3" in result.reason


def test_stop_on_never_started_object_refuses_and_names_why():
    process = BackendProcess()
    assert process.started is False
    assert process.pid is None
    result = process.stop()
    assert result.stopped is False
    assert "never started" in result.reason
    assert result.exit_code is None


def test_stop_is_idempotent(tmp_path):
    process = start_backend(
        _paths(tmp_path),
        [sys.executable, "-c", "pass"],
        prober=lambda port: ProbeResult(PROBE_FREE),
    )
    try:
        first = process.stop(timeout_s=10.0)
        second = process.stop(timeout_s=10.0)
        assert first.stopped is True
        assert second.stopped is True  # no raise, honest answer
    finally:
        if process.is_alive():
            process.stop(timeout_s=10.0)


def test_stop_reports_exit_code_of_already_exited_child(tmp_path):
    paths = _paths(tmp_path)
    process = start_backend(
        paths, [sys.executable, "-c", "pass"], prober=lambda port: ProbeResult(PROBE_FREE)
    )
    try:
        process.popen.wait(timeout=10)
        result = process.stop()
        assert result.stopped is True
        assert result.exit_code == 0
    finally:
        if process.is_alive():
            process.stop(timeout_s=10.0)


# ---------------------------------------------------------------------------
# Parent-owned hardening: wrong types are refusals, and a child that dies in
# the startup grace is reported dead with its code and its log, never announced
# as started.


def test_build_argv_refuses_wrong_types_with_a_clean_reason(tmp_path):
    paths = _paths(tmp_path)
    cases = (
        ({"fps": "30"}, "fps"),
        ({"fps": None}, "fps"),
        ({"fps": 30.5}, "fps"),
        ({"camera": "0"}, "camera"),
        ({"camera": 1.5}, "camera"),
        ({"host": ""}, "host"),
        ({"host": None}, "host"),
    )
    for kwargs, offending in cases:
        with pytest.raises(BackendError) as excinfo:
            build_argv(paths, **kwargs)
        assert offending in str(excinfo.value), kwargs


def test_start_backend_reports_a_child_that_died_inside_the_grace(tmp_path):
    paths = _paths(tmp_path)
    process = start_backend(
        paths, [sys.executable, "-c", "raise SystemExit(3)"], prober=None
    )
    assert process.started is True
    assert process.is_alive() is False
    assert process.exit_code() == 3
    assert "exited immediately" in process.reason
    assert "exit code 3" in process.reason
    assert str(paths.log_path) in process.reason
    assert process.log_handle is None  # the handle is not leaked


def test_start_backend_does_not_cry_death_for_a_live_child(tmp_path):
    paths = _paths(tmp_path)
    process = None
    try:
        process = start_backend(
            paths, [sys.executable, "-c", "import time; time.sleep(60)"], prober=None
        )
        assert process.is_alive() is True
        assert "exited immediately" not in process.reason
        assert "backend started" in process.reason
    finally:
        if process is not None and process.is_alive():
            process.stop(timeout_s=10.0)

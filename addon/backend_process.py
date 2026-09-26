"""Pure launcher core for the Blender-native plugin: build the command, start
the backend as a hidden child process, and stop only what this add-on started.

No bpy imports here on purpose: this module runs under pytest on a Python
without Blender, and the UI unit (P4) is the only bpy-side caller.

Rules this module enforces (frozen contract, odd/tasks/blender-native-plugin.md
P2):

- Never a silent fallback. An unset ``repo_root``, a missing interpreter or a
  missing ``run_capture.py`` refuses by raising :class:`BackendError` with the
  exact missing path. Capability is never decided by a ``PATH`` probe: a
  missing venv interpreter is the user's problem to see, not something to
  paper over with ``shutil.which("python")``.
- The command line is built by a pure function and handed to ``Popen`` as a
  list. ``shell=True`` is forbidden.
- Hidden start on Windows: ``CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP``.
  This feature exists partly because the ``.cmd`` flow pops consoles.
- The log directory may be missing (a fresh clone has no ``soak_output/``):
  ``start_backend`` creates it instead of failing.
- Never start a second camera consumer: when the prober's answer for the
  dashboard port is anything other than ``PROBE_FREE``, nothing is started and
  the reason says why.
- Stop is a tree kill followed by a bounded wait. A child the add-on did not
  start is never killed by the add-on, and a stop that did not stop says so.
- A child that dies inside the short startup grace is reported as dead, with its
  exit code and the log path, instead of being announced as started: a child
  that dies on its first line is the loudest failure of this whole feature, and
  it must not leave a green-looking panel behind.
- Every refusal is a :class:`BackendError` naming the offending value, even for
  a wrong TYPE (``fps="30"`` from a future preference must not surface as a bare
  ``TypeError`` traceback in Blender's console).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, NamedTuple, Optional

PROBE_FREE = "free"
PROBE_DASHBOARD = "dashboard"
PROBE_STRANGER = "stranger"


class BackendError(ValueError):
    """Every refusal raises this; the message names the exact missing or offending thing."""


@dataclass(frozen=True)
class BackendPaths:
    repo_root: Path
    python: Path
    script: Path
    log_path: Path


@dataclass(frozen=True)
class StopResult:
    stopped: bool
    reason: str
    exit_code: Optional[int]


class ProbeResult(NamedTuple):
    state: str
    detail: str = ""


_ENGINES = ("mediapipe", "openseeface")


def resolve_paths(
    repo_root: Any,
    *,
    python_executable: Any = None,
    script: Any = None,
    log_path: Any = None,
) -> BackendPaths:
    """Resolve the four paths the launcher needs, refusing instead of guessing.

    Defaults live inside ``repo_root``; each is overridable by keyword. The
    interpreter and the script must exist. The log's directory may be missing
    (a fresh clone has no ``soak_output/``): ``start_backend`` creates it.
    """
    if repo_root is None or not str(repo_root).strip():
        raise BackendError(
            "no RealCapture repository configured: set the repository folder in "
            "the RealCapture add-on preferences"
        )
    root = Path(str(repo_root)).expanduser()
    if not root.is_dir():
        raise BackendError(
            f"RealCapture repository does not exist or is not a directory: {root.resolve()}"
        )
    root = root.resolve()
    python = Path(str(python_executable)) if python_executable else root / "backend" / ".venv" / "Scripts" / "python.exe"
    script_path = Path(str(script)) if script else root / "backend" / "run_capture.py"
    log = Path(str(log_path)) if log_path else root / "soak_output" / "backend.log"
    python = python.resolve()
    script_path = script_path.resolve()
    log = log.resolve()
    if not python.is_file():
        # Deliberately no shutil.which("python") fallback: the exact missing path
        # is the diagnostic, and a PATH interpreter would hide the broken venv.
        raise BackendError(f"backend interpreter not found: {python}")
    if not script_path.is_file():
        raise BackendError(f"backend script not found: {script_path}")
    return BackendPaths(repo_root=root, python=python, script=script_path, log_path=log)


def build_environment(base_env: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of ``base_env`` plus ``PYTHONUNBUFFERED=1`` and nothing else.

    Unbuffered stdout/stderr is what makes the log get lines promptly; no
    secrets, no credential juggling.
    """
    env = dict(base_env)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _check_port(name: str, port: Any) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise BackendError(
            f"{name} must be an integer in 1..65535, got {port!r}"
        )


def _check_int(name: str, value: Any, minimum: Optional[int] = None) -> None:
    """Refuse a non-integer or out-of-range integer with a clean reason."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackendError(f"{name} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise BackendError(f"{name} must be >= {minimum}, got {value!r}")


def build_argv(
    paths: BackendPaths,
    *,
    engine: str = "mediapipe",
    camera: int = 0,
    fps: int = 30,
    host: str = "127.0.0.1",
    udp_port: int = 11111,
    dashboard_port: int = 8765,
    stream_fps: Optional[float] = None,
) -> list[str]:
    """Build the exact argv for ``Popen(..., shell=False)``: every element a str.

    The flags mirror ``backend/run_capture.py::parse_args``; the round-trip
    through that real parser is pinned by tests. Refusals raise
    :class:`BackendError` naming the offending value.
    """
    if engine not in _ENGINES:
        raise BackendError(
            f"unknown engine {engine!r}: expected one of {', '.join(_ENGINES)}"
        )
    _check_int("camera", camera, 0)
    _check_int("fps", fps, 1)
    if not isinstance(host, str) or not host.strip():
        raise BackendError(
            f"host must be a non-empty address, got {host!r} (the pipeline sends to "
            "its own machine, so 127.0.0.1 is the normal value)"
        )
    if dashboard_port == 0:
        raise BackendError(
            "dashboard_port 0 is refused: the panel's lights come from the "
            "dashboard, so a dashboard port is required"
        )
    _check_port("udp_port", udp_port)
    _check_port("dashboard_port", dashboard_port)
    if stream_fps is not None:
        if not isinstance(stream_fps, (int, float)) or isinstance(stream_fps, bool) or stream_fps <= 0:
            raise BackendError(f"stream_fps must be > 0, got {stream_fps!r}")
    argv = [
        str(paths.python),
        str(paths.script),
        "--engine", engine,
        "--camera", str(camera),
        "--fps", str(fps),
        "--host", str(host),
        "--port", str(udp_port),
        "--dashboard", str(dashboard_port),
    ]
    if stream_fps is not None:
        # No clamping here: the backend owns the stream-fps cap.
        argv += ["--stream-fps", str(float(stream_fps))]
    return argv


def _dashboard_port_of(argv: list[str]) -> Optional[int]:
    """Extract the dashboard port from a built argv; None when absent."""
    for index, item in enumerate(argv):
        if item == "--dashboard" and index + 1 < len(argv):
            try:
                return int(argv[index + 1])
            except ValueError as exc:
                raise BackendError(
                    f"--dashboard value is not an integer: {argv[index + 1]!r}"
                ) from exc
    return None


class BackendProcess:
    """Handle for the child this add-on started (or deliberately did not)."""

    def __init__(
        self,
        popen: Optional[subprocess.Popen] = None,
        *,
        log_handle: Any = None,
        reason: str = "",
    ) -> None:
        self.popen = popen
        self.log_handle = log_handle
        self.pid: Optional[int] = popen.pid if popen is not None else None
        self.started: bool = popen is not None
        self.reason: str = reason

    def is_alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def exit_code(self) -> Optional[int]:
        """The child's exit code, or ``None`` while it is still running."""
        if self.popen is None:
            return None
        return self.popen.poll()

    def _close_log(self) -> None:
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            except OSError:
                pass
            self.log_handle = None

    def stop(self, *, timeout_s: float = 10.0) -> StopResult:
        """Kill the child tree and wait a bounded time; idempotent.

        A child this object never started is never killed: the refusal says so.
        """
        if self.popen is None:
            return StopResult(
                stopped=False,
                reason=(
                    "backend was never started by the add-on, so the add-on will "
                    "not kill it"
                ),
                exit_code=None,
            )
        popen = self.popen
        code = popen.poll()
        if code is not None:
            self._close_log()
            return StopResult(
                stopped=True,
                reason=f"backend process already exited (exit code {code})",
                exit_code=code,
            )
        kill_report = _kill_tree(popen)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            code = popen.poll()
            if code is not None:
                self._close_log()
                return StopResult(
                    stopped=True,
                    reason=f"backend stopped (exit code {code})",
                    exit_code=code,
                )
            time.sleep(0.05)
        self._close_log()
        return StopResult(
            stopped=False,
            reason=(
                f"backend still running after waiting {timeout_s:.1f} s; "
                f"kill report: {kill_report or 'no output'}"
            ),
            exit_code=None,
        )


def _kill_tree(popen: subprocess.Popen) -> str:
    """Kill the child's whole tree and return any output the kill produced."""
    if sys.platform == "win32":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(popen.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                shell=False,
            )
        except OSError as exc:
            return f"taskkill failed to run: {exc}"
        return ((completed.stdout or "") + (completed.stderr or "")).strip()
    # POSIX: the child was started as its own process group leader
    # (start_new_session=True), so one signal reaches the whole tree.
    try:
        os.killpg(popen.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as exc:
        return f"killpg failed: {exc}"
    return ""


def _hidden_creation_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def start_backend(
    paths: BackendPaths,
    argv: list[str],
    *,
    prober: Optional[Callable[[Optional[int]], Any]] = None,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    startup_grace_s: float = 0.25,
) -> BackendProcess:
    """Probe the dashboard port, then start the backend as a hidden child.

    ``prober`` receives the dashboard port carried by ``argv`` and returns
    anything with ``.state``/``.detail`` (or raises). Nothing is started unless
    the answer is ``PROBE_FREE``. ``prober=None`` means the caller deliberately
    skipped the check: the start proceeds and the reason says the port was not
    checked. ``popen_factory`` exists so tests can observe the exact kwargs.
    ``startup_grace_s`` is the short window in which a child that died on its
    first line is reported with its exit code and the log path instead of being
    announced as started.
    """
    port = _dashboard_port_of(argv)
    if prober is not None:
        try:
            probe = prober(port)
        except Exception as exc:  # noqa: BLE001 - any prober failure must not start anything
            return BackendProcess(
                reason=(
                    f"backend not started: the dashboard port {port} could not "
                    f"be checked ({exc})"
                )
            )
        state = getattr(probe, "state", None)
        detail = getattr(probe, "detail", "") or ""
        if state == PROBE_DASHBOARD:
            return BackendProcess(
                reason=(
                    f"backend not started: another RealCapture backend is already "
                    f"running and is being reused (dashboard port {port}"
                    f"{f'; {detail}' if detail else ''})"
                )
            )
        if state == PROBE_STRANGER:
            return BackendProcess(
                reason=(
                    f"backend not started: port {port} is held by something that "
                    f"is not this dashboard ({detail or 'unexpected answer'})"
                )
            )
        if state != PROBE_FREE:
            return BackendProcess(
                reason=(
                    f"backend not started: prober returned unknown state "
                    f"{state!r} for port {port}"
                )
            )
    log_dir = paths.log_path.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    log_handle = open(paths.log_path, "ab")  # noqa: SIM115 - lifetime owned by BackendProcess
    kwargs: dict[str, Any] = dict(
        cwd=str(paths.repo_root),
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=_hidden_creation_flags(),
        shell=False,
    )
    if sys.platform != "win32":
        # The POSIX half of the tree kill: make the child a group leader so
        # stop() can signal the whole tree with one killpg.
        kwargs["start_new_session"] = True
    try:
        popen = popen_factory(argv, **kwargs)
    except Exception as exc:  # noqa: BLE001 - report, never half-start
        log_handle.close()
        return BackendProcess(
            reason=f"backend not started: the process could not be launched ({exc})"
        )
    checked = "checked" if prober is not None else "not checked"
    process = BackendProcess(
        popen,
        log_handle=log_handle,
        reason=(
            f"backend started (pid {popen.pid}); dashboard port {port} was {checked}"
        ),
    )
    if startup_grace_s > 0:
        deadline = time.monotonic() + startup_grace_s
        while time.monotonic() < deadline and popen.poll() is None:
            time.sleep(0.02)
        code = popen.poll()
        if code is not None:
            # Append, never replace: the admission that the port was not checked
            # must survive the news that the child is already dead.
            process.reason = (
                f"{process.reason}; it exited immediately (exit code {code}); "
                f"see the log: {paths.log_path}"
            )
            process._close_log()
    return process

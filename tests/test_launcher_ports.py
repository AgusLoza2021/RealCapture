"""Every %PORT% a launcher expands must be defined, numeric and real.

The defect this file exists for: ``camera-to-rig.cmd`` expanded ``%PORT%`` in
the command that starts the camera pipeline and in the command that starts
Blender, but never defined it. ``cmd.exe`` expands an undefined variable to
nothing, so the backend was invoked as ``--port`` with no value and died with
``argument --port: expected one argument``. Blender still opened, the character
still loaded, and not one packet ever arrived - a broken run that looks exactly
like a working one with nobody in front of the camera.

This was the headline demo of the repository, and nothing could catch it: the
launcher's exit code was never checked by anything, and the failure happened
inside a second console window.

That is why these checks are executable instead of textual:

1. a launcher that expands ``%PORT%`` must define it before the first use;
2. the definition must be a plain port number;
3. camera-to-rig's value must equal ``backend/run_capture.py``'s own ``--port``
   default, so the launcher and the code cannot drift apart in silence;
4. the defined value must actually be expanded, so a constant nobody reads
   cannot satisfy this file (the same defect family as a state nobody reads).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The two launchers of the one-command flows. Each owns its own meaning of the
# name: camera-to-rig.cmd owns the UDP port the addon listens on,
# control-room.cmd owns the dashboard port a browser connects to.
LAUNCHERS = ("camera-to-rig.cmd", "control-room.cmd")

PORT_USE = "%PORT%"
PORT_DEFINITION = re.compile(r'set "PORT=([0-9]+)"')


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8", errors="replace")


def _executable_lines(name: str) -> str:
    """The lines cmd.exe would run: a REM comment defines nothing and uses
    nothing, and a launcher that only mentions the port in prose has not
    configured it."""
    lines = [
        line
        for line in _read(name).splitlines()
        if not line.strip().upper().startswith("REM")
    ]
    return "\n".join(lines)


def _definition(name: str) -> re.Match[str]:
    match = PORT_DEFINITION.search(_read(name))
    assert match is not None, (
        f"{name} expands {PORT_USE} but never defines PORT; cmd.exe expands an "
        "undefined variable to nothing, so the flag after it gets no value and "
        "the process dies with a usage error"
    )
    return match


def test_a_launcher_that_expands_port_defines_it_first() -> None:
    for name in LAUNCHERS:
        code = _executable_lines(name)
        if PORT_USE not in code:
            continue
        assignment = code.find('set "PORT=')
        assert assignment != -1, (
            f"{name} expands {PORT_USE} but never assigns PORT; cmd.exe expands "
            "an undefined variable to nothing, so the flag after it gets no "
            "value and the process dies with a usage error"
        )
        assert assignment < code.index(PORT_USE), (
            f"{name} expands {PORT_USE} before assigning it"
        )


def test_the_defined_port_is_a_plain_number_in_range() -> None:
    for name in LAUNCHERS:
        value = int(_definition(name).group(1))
        assert 1 <= value <= 65535, f"{name} sets PORT={value}, not a usable port"


def test_camera_to_rig_udp_port_matches_the_backend_default() -> None:
    from backend.run_capture import parse_args

    launcher_port = int(_definition("camera-to-rig.cmd").group(1))
    backend_port = parse_args([]).port
    assert launcher_port == backend_port, (
        f"camera-to-rig.cmd sends to UDP {launcher_port} while "
        f"backend/run_capture.py defaults to {backend_port}; the addon listens "
        "on the port the launcher chooses, so the two must agree"
    )


def test_each_defined_port_is_actually_expanded() -> None:
    for name in LAUNCHERS:
        assert PORT_USE in _executable_lines(name), (
            f"{name} defines PORT but never expands it; a constant nobody reads "
            "is not a configured port"
        )


def test_control_room_uses_its_port_for_both_the_backend_and_the_probe() -> None:
    text = _executable_lines("control-room.cmd")
    assert "--dashboard %PORT%" in text, (
        "control-room.cmd must pass its port to the backend dashboard"
    )
    assert "127.0.0.1:%PORT%/" in text, (
        "control-room.cmd must probe the same port it passed to the backend"
    )


class TestPidOwnershipContract:
    """C3 safety fix: the capture pipeline is stopped by recorded PID only.

    Live evidence: stopping by console-window title matched the shared
    ``WindowsTerminal.exe`` host and killed every other tab inside it. The
    ownership contract pinned here:

    1. the pipeline is started through ``Start-Process -PassThru``, so the
       launcher holds the concrete PID of a process it created itself;
    2. the PID is recorded at launch, and a launch that yields no PID fails
       closed (exit 6) - an empty value must never reach a stop command;
    3. every cleanup path calls one shared stop routine that stops only the
       recorded PID and its descendants, and only after positive identity
       validation: the recorded PID's command line must still contain the
       exact launch command, so a recycled PID owned by an unrelated process
       is left alone.
    """

    def test_no_title_or_image_name_kill_remains(self) -> None:
        for name in LAUNCHERS:
            text = _read(name).lower()
            assert "taskkill" not in text, (
                f"{name} still uses taskkill; the only sanctioned stop is the "
                "recorded-PID stop routine (:stop_capture), because title and "
                "image-name filters can match the shared Windows Terminal host "
                "or unrelated processes"
            )
            assert "windowtitle" not in text, (
                f"{name} still matches a window title; that filter killed the "
                "shared WindowsTerminal.exe host and collateral tabs"
            )

    def test_the_pipeline_pid_is_recorded_at_launch(self) -> None:
        for name in LAUNCHERS:
            text = _read(name)
            assert "-PassThru" in text, (
                f"{name} must start the pipeline through Start-Process -PassThru "
                "so the launcher owns the concrete PID it will later stop"
            )
            assert 'set "CAPTURE_PID=%%A"' in text, (
                f"{name} never records the pipeline PID; without a recorded PID "
                "the only stops left are guesses (titles, image names)"
            )
            assert "$p.StartTime.ToUniversalTime().Ticks" in text, (
                f"{name} never records the wrapper's start time; the PID alone "
                "cannot reject a recycled PID whose command line matches"
            )
            assert 'set "CAPTURE_PID_BORN=%%B"' in text, (
                f"{name} never records the launch-time start-time identity"
            )

    def test_the_launch_record_is_validated_as_two_decimal_values(self) -> None:
        for name in LAUNCHERS:
            text = _read(name)
            start = text.index('usebackq tokens=1,2')
            region = text[start:text.index("call :stop_capture")]
            for value in ("CAPTURE_PID", "CAPTURE_PID_BORN"):
                assert f"if not defined {value}" in region, (
                    f"{name} never checks that the recorded {value} exists; a "
                    "missing record must fail closed, not reach a stop command"
                )
                assert f"echo %{value}%| findstr" in region, (
                    f"{name} never checks that the recorded {value} is a plain "
                    "decimal number before using it"
                )
            assert "exit /b 6" in region, (
                f"{name} must exit 6 when the launch record is missing or malformed"
            )

    def test_a_launch_without_a_pid_fails_closed(self) -> None:
        for name in LAUNCHERS:
            text = _read(name)
            guard = "if not defined CAPTURE_PID"
            assert guard in text, (
                f"{name} must fail closed when the launch yields no PID: an "
                "undefined value must never reach a stop command"
            )
            assert "exit /b 6" in text, (
                f"{name} must exit with a distinct code when the launch "
                "yields no PID"
            )
            assert text.index(guard) < text.index("call :stop_capture"), (
                f"{name} reaches its stop path before guarding against a "
                "missing PID"
            )

    def test_every_cleanup_path_stops_the_recorded_pid(self) -> None:
        expected_calls = {"camera-to-rig.cmd": 1, "control-room.cmd": 2}
        for name in LAUNCHERS:
            calls = _read(name).count("call :stop_capture")
            assert calls == expected_calls[name], (
                f"{name} calls the recorded-PID stop routine {calls} time(s), "
                f"expected {expected_calls[name]}: every cleanup path (normal, "
                "startup failure, timeout, post-Blender) must stop only the "
                "recorded PID"
            )

    def test_the_stop_routine_guards_validates_and_stops_the_tree(self) -> None:
        for name in LAUNCHERS:
            text = _read(name)
            assert text.count("\n:stop_capture") == 1, (
                f"{name} must define exactly one shared stop routine"
            )
            routine = text[text.index("\n:stop_capture"):]
            guard = "if not defined CAPTURE_PID"
            assert guard in routine, (
                f"{name}'s stop routine must refuse to run without a recorded PID"
            )
            assert routine.index(guard) < routine.index("Stop-Process -Id"), (
                f"{name}'s stop routine can reach its stop command with an "
                "undefined PID"
            )
            assert "RC_CAPTURE_ARGS" in routine and "IndexOf" in routine, (
                f"{name}'s stop routine must positively validate the recorded "
                "PID's command line against the exact launch command before "
                "stopping it (the PID-reuse guard)"
            )
            assert "ParentProcessId" in routine, (
                f"{name}'s stop routine must stop descendants of the recorded "
                "PID so the python child of the wrapper console does not survive"
            )
            assert "Stop-Process -Id" in routine

    def test_the_stop_routine_rejects_recycled_pids_and_foreign_processes(self) -> None:
        for name in LAUNCHERS:
            routine = _read(name)[_read(name).index("\n:stop_capture"):]
            live = routine.index("Get-Process -Id $env:CAPTURE_PID")
            born = routine.index("$born -eq $env:CAPTURE_PID_BORN")
            ident = routine.index("-ieq $env:ComSpec")
            exact = routine.index("IndexOf($env:RC_CAPTURE_ARGS")
            kill = routine.index("Stop-Tree $env:CAPTURE_PID")
            assert live < born < ident < exact < kill, (
                f"{name}'s stop routine must validate, in order: the live process "
                "exists, the recorded start time still matches it (this rejects a "
                "recycled PID even when the command line matches), the executable "
                "identity (cmd.exe at ComSpec), and the exact capture command - "
                "before any tree stop runs"
            )
            assert "exit 0" in routine and "exit 1" in routine, (
                f"{name}'s stop routine must report its outcome through an "
                "explicit exit status"
            )

    def test_the_stop_routine_guards_numeric_values_before_stopping(self) -> None:
        for name in LAUNCHERS:
            routine = _read(name)[_read(name).index("\n:stop_capture"):]
            pid_num = routine.index("echo %CAPTURE_PID%| findstr")
            born_num = routine.index("echo %CAPTURE_PID_BORN%| findstr")
            stop = routine.index("Stop-Process -Id")
            assert pid_num < born_num < stop, (
                f"{name}'s stop routine must check both recorded values as plain "
                "decimal numbers before the stop command can see them"
            )

    def test_every_caller_checks_the_stop_status(self) -> None:
        expected_calls = {"camera-to-rig.cmd": 1, "control-room.cmd": 2}
        for name in LAUNCHERS:
            text = _read(name)
            regions = []
            start = 0
            while True:
                idx = text.find("call :stop_capture", start)
                if idx == -1:
                    break
                nxt = text.find("\n:", idx)
                regions.append(text[idx:nxt if nxt != -1 else len(text)])
                start = idx + 1
            assert len(regions) == expected_calls[name], (
                f"{name} gained or lost a cleanup path calling the stop routine"
            )
            for region in regions:
                assert "if errorlevel 1" in region, (
                    f"{name} calls :stop_capture without checking its status; "
                    "a failed stop must never be reported as a successful one"
                )
                assert "could not be confirmed stopped" in region and "exit /b 7" in region, (
                    f"{name} must print an actionable message and exit 7 when "
                    "the stop status reports failure"
                )

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

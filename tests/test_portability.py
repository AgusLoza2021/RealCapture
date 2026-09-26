"""Portability contract: the launchers, the Blender tools, and the backend.

Published code must run on any Windows machine: no author-specific paths, no
silent fallbacks, no advertised behaviour that does not exist. These tests
read the real files from disk and pin the frozen contract:

- ``RC_MPFB_ROOT`` / ``RC_BLENDER`` / ``RC_CHARACTER`` with the documented
  defaults, and ``local.cmd`` (gitignored, optional) sourced by both launchers
  BEFORE any default is resolved;
- launcher exit codes, one cause each: 2 = Blender not found, 3 = character
  .blend not found, 4 = backend virtualenv not found, 5 = usage error;
- the character .blend is resolved by ``tools/blender_mpfb_live.py`` in the
  order --blend, ``RC_CHARACTER``, ``RC_MPFB_ROOT`` - never a hardcoded user
  path, and never a silent fallback to a different file;
- ``backend/run_capture.py`` no longer advertises the no-op ``--visualize``
  flag: the live preview lives in the Control Room dashboard.

The project rule behind all of this: a broken or absent signal must say WHY
in plain text and never look healthy. Every assertion here exists because
violating it once looked like success.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CAMERA_TO_RIG = "camera-to-rig.cmd"
CONTROL_ROOM = "control-room.cmd"
LAUNCHERS = (CAMERA_TO_RIG, CONTROL_ROOM)
LIVE_TOOL = "tools/blender_mpfb_live.py"
DEMO_TOOL = "tools/blender_mpfb_demo.py"
RUN_CAPTURE = "backend/run_capture.py"

# Every file this portability pass owns: none of them may carry the author's
# machine into a stranger's machine.
PORTABILITY_SURFACES = (
    CAMERA_TO_RIG,
    CONTROL_ROOM,
    LIVE_TOOL,
    DEMO_TOOL,
    RUN_CAPTURE,
)


def _read(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    assert path.exists(), f"{rel_path} is missing from the repository"
    return path.read_text(encoding="utf-8", errors="replace")


# -- no author machine paths anywhere -----------------------------------------


def test_no_author_name_or_user_profile_paths_in_any_surface() -> None:
    for rel in PORTABILITY_SURFACES:
        text = _read(rel)
        assert "Lozita" not in text, (
            f"{rel} still contains the author's user name; it cannot run on "
            "any other machine"
        )
        assert not re.search(r"C:\\\\Users\\\\", text), (
            f"{rel} contains a machine-specific C:\\Users\\... path"
        )
        assert "C:/Users" not in text, (
            f"{rel} contains a machine-specific C:/Users/... path"
        )


def test_no_leftover_temporary_mpfb_root_names_anywhere() -> None:
    """The old ad-hoc root was ...\\Temp\\rc_mpfb; the published contract is
    RC_MPFB_ROOT (default %LOCALAPPDATA%\\RealCapture\\mpfb)."""
    for rel in PORTABILITY_SURFACES + LAUNCHERS:
        assert "rc_mpfb" not in _read(rel), (
            f"{rel} still references the author's temporary rc_mpfb root"
        )


# -- launchers: local.cmd, discovery, waiting, exit codes ---------------------


def test_launchers_source_local_cmd_before_resolving_any_default() -> None:
    for rel in LAUNCHERS:
        text = _read(rel)
        assert "local.cmd" in text, f"{rel} never sources local.cmd"
        assert 'if exist "%~dp0local.cmd" call "%~dp0local.cmd"' in text, (
            f"{rel} must source local.cmd only when it exists; its absence is "
            "normal, not a failure"
        )
        # camera-to-rig resolves the RC_* defaults; control-room's first
        # default is the dashboard port. local.cmd must be sourced before
        # either can run.
        if "RC_MPFB_ROOT=" in text:
            first_default = text.index("RC_MPFB_ROOT=")
        else:
            first_default = text.index('set "PORT=8765"')
        assert text.index("local.cmd") < first_default, (
            f"{rel} resolves defaults before local.cmd can override them"
        )


def test_launchers_contain_no_hardcoded_machine_paths() -> None:
    for rel in LAUNCHERS:
        text = _read(rel)
        assert not re.search(r"[A-Za-z]:\\", text), (
            f"{rel} contains a drive-absolute path; it must stay "
            "machine-independent"
        )
        assert "C:\\Program Files" not in text
        assert "Blender 4.5" not in text, (
            f"{rel} pins the author's Blender version instead of discovering it"
        )


def test_camera_to_rig_discovers_blender_through_the_contract() -> None:
    text = _read(CAMERA_TO_RIG)
    assert "RC_BLENDER" in text, "RC_BLENDER override is not honoured"
    assert "%LOCALAPPDATA%\\RealCapture\\mpfb" in text, (
        "the documented RC_MPFB_ROOT default is missing"
    )
    assert "where blender" in text, "PATH discovery for blender.exe is missing"
    assert "Blender Foundation\\Blender *" in text, (
        "the standard install folders are not globbed for Blender installs"
    )
    assert "ProgramFiles(x86)" in text, (
        "the 32-bit Program Files root is not searched for Blender"
    )


def test_launchers_wait_with_ping_and_never_use_timeout_t() -> None:
    for rel in LAUNCHERS:
        text = _read(rel)
        assert "timeout /t" not in text.lower(), (
            f"{rel} uses timeout /t: on a PATH carrying git-bash/MSYS it "
            "resolves to the non-Windows binary and the wait silently vanishes"
        )
        assert re.search(r"ping -n \d+ 127\.0\.0\.1 >nul", text), (
            f"{rel} lost the ping-based sleep primitive"
        )


def test_missing_virtualenv_is_a_hard_failure_with_exit_4() -> None:
    for rel in LAUNCHERS:
        text = _read(rel)
        assert "backend\\.venv\\Scripts\\python.exe" in text, (
            f"{rel} does not use the project virtualenv interpreter"
        )
        assert "exit /b 4" in text, (
            f"{rel} does not hard-fail with exit 4 on a missing virtualenv"
        )
        assert not re.search(r"set\s+\"?PY=python\"?\s*$", text, re.MULTILINE), (
            f"{rel} silently falls back to a system python - exactly the "
            "success-looking silence this project forbids"
        )


def test_blender_and_character_failures_exit_2_and_3() -> None:
    text = _read(CAMERA_TO_RIG)
    assert "exit /b 2" in text, "Blender-not-found must exit 2"
    assert "exit /b 3" in text, "character-not-found must exit 3"
    # The message must name the missing thing AND the variable that fixes it.
    assert "RC_BLENDER" in text
    assert "RC_CHARACTER" in text


def test_usage_errors_exit_5_in_both_launchers() -> None:
    for rel in LAUNCHERS:
        assert "exit /b 5" in _read(rel), (
            f"{rel} does not exit 5 on a usage error (5 = usage error, one "
            "cause per exit code)"
        )


def test_launcher_headers_document_the_exit_codes() -> None:
    for rel in LAUNCHERS:
        text = _read(rel)
        assert "Exit codes" in text, f"{rel} header does not document exit codes"
        lower = text.lower()
        assert "usage error" in lower
        assert "virtualenv" in lower


# -- tools/blender_mpfb_live.py: character resolution -------------------------


def test_live_tool_resolves_the_character_through_the_contract() -> None:
    src = _read(LIVE_TOOL)
    assert "--blend" in src, "no explicit --blend override exists"
    assert "RC_CHARACTER" in src and "RC_MPFB_ROOT" in src, (
        "the environment part of the resolution order is missing"
    )
    assert "DEFAULT_BLEND" not in src, (
        "a hardcoded default character path still exists"
    )
    assert "_resolve_blend_path" in src and "isfile" in src, (
        "resolution must land on a candidate that actually exists on disk"
    )


def test_live_tool_teaches_the_contract_not_the_authors_machine() -> None:
    src = _read(LIVE_TOOL)
    assert "<RC_MPFB_ROOT>" in src, (
        "the help text must use generic placeholders for the env contract"
    )
    assert "BLENDER_USER_CONFIG" in src and "BLENDER_USER_EXTENSIONS" in src, (
        "the isolated-config env documentation regressed out"
    )


# -- tools/blender_mpfb_demo.py: honest setup instructions --------------------


def test_demo_doc_does_not_reference_the_missing_generator() -> None:
    src = _read(DEMO_TOOL)
    assert "gen_character.py" not in src, (
        "the demo doc still tells readers to run a generator script that does "
        "not exist anywhere in the repository"
    )
    assert "RC_CHARACTER" in src, (
        "the demo doc must name the real way to point at the character .blend"
    )
    assert "RC_MPFB_ROOT" in src


# -- backend/run_capture.py: no phantom --visualize flag ----------------------


def test_run_capture_parser_rejects_visualize() -> None:
    from backend.run_capture import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--visualize"])


def test_run_capture_help_does_not_advertise_visualize() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / RUN_CAPTURE), "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    assert "--visualize" not in result.stdout, (
        "run_capture.py still advertises a live preview flag that does "
        "nothing; the live preview is the Control Room dashboard"
    )

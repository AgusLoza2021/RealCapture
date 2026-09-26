"""Doc-pinning tests for the control-room launcher and its short doc (W6).

These tests read the launcher, the doc, and the README as text and fail if a
lesson regresses:

- no ``timeout /t`` anywhere: on a PATH carrying git-bash/MSYS tools,
  ``timeout /t 6`` resolves to the non-Windows binary and fails with
  "invalid time interval '/t'", silently removing the wait;
- the interpreter is resolved relative to the script (``%~dp0``) from the
  project virtualenv only, with no machine-absolute path and no silent
  fallback to a system Python;
- the browser is opened in app mode only after the dashboard answers, with a
  plain ``start ""`` fallback when Edge is not on PATH.

The doc assertions keep the human-facing explanations from being dropped:
the four light states and the reason for each documented non-green case.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "control-room.cmd"
DOC = REPO_ROOT / "docs" / "control-room.md"
README = REPO_ROOT / "README.md"


def _launcher_text() -> str:
    assert LAUNCHER.exists(), "control-room.cmd is missing from the repo root"
    text = LAUNCHER.read_text(encoding="utf-8", errors="replace")
    assert text.strip(), "control-room.cmd exists but is empty"
    return text


def _doc_text() -> str:
    assert DOC.exists(), "docs/control-room.md is missing"
    return DOC.read_text(encoding="utf-8", errors="replace")


class TestLauncherContract:
    def test_launcher_exists_and_is_non_empty(self) -> None:
        _launcher_text()

    def test_no_timeout_t_and_the_ping_sleep_is_present(self) -> None:
        text = _launcher_text()
        assert "timeout /t" not in text.lower(), (
            "timeout /t regressed in: on a PATH carrying git-bash/MSYS it "
            "resolves to the non-Windows binary and the wait silently vanishes"
        )
        assert re.search(r"ping -n \d+ 127\.0\.0\.1 >nul", text), (
            "the ping-based sleep primitive is missing"
        )

    def test_interpreter_is_resolved_relative_to_the_script(self) -> None:
        text = _launcher_text()
        assert "%~dp0" in text, "the script must resolve paths relative to itself"
        assert "backend\\.venv\\Scripts\\python.exe" in text, (
            "the launcher must use the project virtualenv interpreter"
        )
        assert "--dashboard" in text, "the launcher must serve the dashboard"
        assert not re.search(r"[A-Za-z]:\\", text), (
            "drive-absolute path found in the launcher; it must stay machine-independent"
        )
        assert "C:\\Users" not in text, "a user-name-specific absolute path regressed in"

    def test_no_silent_fallback_to_system_python(self) -> None:
        text = _launcher_text()
        # camera-to-rig.cmd's defect: 'if not exist "%PY%" set "PY=python"'.
        assert not re.search(r"set\s+\"?PY=python\"?\s*$", text, re.MULTILINE), (
            "the launcher must not fall back to a system python"
        )
        assert "fall back" in text.lower(), (
            "the missing-virtualenv message must say there is no system-python fallback"
        )

    def test_browser_opens_in_app_mode_with_a_plain_start_fallback(self) -> None:
        text = _launcher_text()
        assert "--app=" in text, "app mode (--app=) is missing"
        assert "msedge" in text, "the Edge app-mode launcher is missing"
        assert 'start ""' in text, "the plain start fallback is missing"

    def test_no_browser_flag_is_supported(self) -> None:
        assert "--no-browser" in _launcher_text()

    def test_edge_is_found_by_install_path_not_only_by_path(self) -> None:
        """A stock Windows install puts Edge under Program Files without adding
        it to PATH, so a PATH check alone silently degrades app mode to a
        browser tab - the exact thing this launcher exists to avoid."""
        text = _launcher_text()

        assert "Microsoft\Edge\Application\msedge.exe" in text
        assert "ProgramFiles" in text
        assert "where msedge" in text  # still the last resort

    def test_a_missing_edge_is_announced_not_hidden(self) -> None:
        text = _launcher_text()

        assert "Microsoft Edge was not found" in text

    def test_failure_path_reports_and_exits_non_zero(self) -> None:
        text = _launcher_text()
        assert "exit /b 3" in text, "the did-not-come-up path must exit 3"
        assert "127.0.0.1" in text.lower() or "antivirus" in text.lower(), (
            "the failure message must name the likely causes"
        )
        assert "taskkill" in text, "every exit path must kill the capture process tree"


class TestDocContract:
    def test_doc_exists(self) -> None:
        _doc_text()

    def test_doc_names_the_launcher_and_the_local_url(self) -> None:
        text = _doc_text()
        assert "control-room.cmd" in text
        assert "127.0.0.1:8765" in text, "the localhost URL of the manual command regressed out"

    def test_doc_explains_all_four_light_states(self) -> None:
        text = _doc_text().lower()
        for word in ("green", "yellow", "red", "unknown"):
            assert word in text, f"the {word.upper()} state is no longer explained"

    def test_doc_pins_the_never_green_on_absent_data_rule(self) -> None:
        text = _doc_text().lower()
        assert "never green" in text, (
            "the rule that a light is never green because the data is absent regressed out"
        )

    def test_doc_keeps_the_reason_for_each_documented_non_green_case(self) -> None:
        text = _doc_text().lower()
        # Green may still carry a useful line: the refused bone path.
        assert "shape keys" in text and "refused" in text, (
            "the green-with-reason example (shape keys only, bone path refused) regressed out"
        )
        # Blender not open -> red.
        assert "not open" in text, "the 'Blender is not open' red case regressed out"
        # Blender open but nothing bound -> yellow.
        assert "nothing is bound" in text, "the 'nothing is bound' yellow case regressed out"
        # Stream stopped overlay.
        assert "stream stopped" in text, "the stream-stopped overlay case regressed out"
        # Camera trouble.
        assert "another program" in text, "the camera-held-by-another-program cause regressed out"

    def test_doc_keeps_the_two_small_promises(self) -> None:
        text = _doc_text().lower()
        assert "never freezes on" in text, (
            "the promise that the preview stops instead of freezing regressed out"
        )
        assert "virtualenv" in text and "third light" in text, (
            "the promise that the window needs only the virtualenv regressed out"
        )

    def test_doc_mentions_the_launcher_options(self) -> None:
        text = _doc_text()
        assert "--no-browser" in text
        assert "--port" in text


class TestReadmeContract:
    def test_readme_points_at_the_launcher_and_the_doc(self) -> None:
        readme = README.read_text(encoding="utf-8", errors="replace")
        assert "control-room.cmd" in readme, "the README no longer points at the launcher"
        assert "docs/control-room.md" in readme, "the README no longer links the doc"


class TestUnknownIsNotRed:
    """UNKNOWN must stay visually distinct from RED. "Not known yet" is not
    "failed", and collapsing them would hide a connection the window has simply
    not heard about behind a failure it did not observe."""

    def _dot_rule(self, state: str) -> str:
        html = (REPO_ROOT / "backend" / "dashboard" / "static" / "index.html").read_text(
            encoding="utf-8", errors="replace"
        )
        match = re.search(r'\.conn\[data-state="%s"\] \.dot \{([^}]*)\}' % state, html)
        assert match, "no .dot rule for state %r" % state
        return match.group(1).strip()

    def test_the_unknown_dot_is_not_drawn_like_the_red_one(self) -> None:
        assert self._dot_rule("unknown") != self._dot_rule("red")
        assert "transparent" in self._dot_rule("unknown")

    def test_doc_does_not_claim_unknown_looks_like_red(self) -> None:
        assert "shown the same way as red" not in _doc_text()
        assert "hollow" in _doc_text()

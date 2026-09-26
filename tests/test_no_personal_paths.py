"""No tracked file may carry the author's own machine paths.

This repository is public. A hardcoded ``C:\\Users\\<someone>`` path in published
code is not a cosmetic wart: the code cannot run on any other machine, and the
failure it produces is a confusing local one. That is the same defect class the
project forbids everywhere else -- a signal that looks healthy while the thing
behind it is broken.

The scan covers every tracked file rather than the few a reviewer happened to
open, and it carries its own anti-vacuity proof: ``test_the_check_detects_a_path``
feeds the finder a file that definitely contains a personal path and asserts it is
reported. A check that cannot fail is not a check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The author's Windows profile name, the shape of any absolute Windows user
# profile path (both separators), and the temporary root the isolated MPFB2
# environment used during development.
PERSONAL_MARKERS = ("Lozita", "C:\\Users\\", "C:/Users/", "rc_mpfb")

# A test that forbids a string has to be able to write that string down, so the
# test tree is excluded from its own scan. Everything else -- addon, backend,
# tools, docs, launchers -- is scanned.
EXCLUDED_PREFIXES = ("tests/",)

# Guards against a scan that silently matched nothing (a renamed root, a broken
# `git ls-files`, a wrong working directory) and therefore passed for free.
MIN_EXPECTED_FILES = 50


def _tracked_files() -> list[Path]:
    """Every tracked file, via git itself: untracked scratch files are not published."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    names = [name for name in result.stdout.split("\0") if name]
    if not names:
        raise AssertionError(
            "git ls-files returned nothing; the personal-path scan would be vacuous"
        )
    return [REPO_ROOT / name for name in names]


def find_personal_paths(
    files: list[Path],
    root: Path = REPO_ROOT,
    excluded_prefixes: tuple[str, ...] = EXCLUDED_PREFIXES,
) -> dict[str, list[str]]:
    """Return {path relative to root: [markers found]} for every offending file.

    Binary and undecodable files are skipped: they cannot carry a reviewable
    hardcoded path, and failing on them would be noise.
    """
    offenders: dict[str, list[str]] = {}
    for path in files:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        if rel.startswith(excluded_prefixes):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = [marker for marker in PERSONAL_MARKERS if marker in text]
        if found:
            offenders[rel] = found
    return offenders


def test_no_tracked_file_carries_a_personal_path() -> None:
    tracked = _tracked_files()
    scanned = [
        path
        for path in tracked
        if not path.relative_to(REPO_ROOT).as_posix().startswith(EXCLUDED_PREFIXES)
    ]
    assert len(scanned) >= MIN_EXPECTED_FILES, (
        f"only {len(scanned)} files were scanned, below the {MIN_EXPECTED_FILES} "
        "expected: the scan is not covering the repository and would pass for free"
    )

    offenders = find_personal_paths(tracked)
    assert not offenders, (
        "tracked files carry the author's machine paths, so the published code "
        "cannot run anywhere else:\n"
        + "\n".join(
            f"  {path}: {', '.join(markers)}" for path, markers in sorted(offenders.items())
        )
    )


def test_the_check_detects_a_path(tmp_path: Path) -> None:
    """Anti-vacuity proof: the finder must actually report a personal path."""
    probe = tmp_path / "probe.txt"
    probe.write_text(
        'BLEND = "C:\\Users\\Someone\\AppData\\Local\\Temp\\rc_mpfb\\character.blend"\n',
        encoding="utf-8",
    )

    reported = find_personal_paths([probe], root=tmp_path, excluded_prefixes=())

    assert "probe.txt" in reported, (
        "the personal-path finder did not report a file that clearly contains a "
        "personal path; every green result from this module is meaningless"
    )
    assert "rc_mpfb" in reported["probe.txt"]
    assert "C:\\Users\\" in reported["probe.txt"]

"""Public-repo hygiene: pin the promises the published documentation makes.

Every assertion here reads the real files from disk, so a documented promise
that drifts — a stale test count, a dead relative link, a leftover
"not published" claim, a missing license notice — fails the suite instead of
shipping to a public repository.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
README_LOWER = README.lower()
GITIGNORE = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_license_file_is_gpl3_with_or_later_notice() -> None:
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3" in license_text
    # The GPL is hard-wrapped, so the "or any later version" application notice in
    # the appendix straddles a line break. Collapse whitespace before matching:
    # a contiguous-substring assertion fails on a file that is perfectly correct.
    collapsed = re.sub(r"\s+", " ", license_text)
    assert (
        "either version 3 of the License, or (at your option) any later version"
        in collapsed
    ), "LICENSE lacks the 'or any later version' application notice"


def test_readme_declares_gpl3_or_later() -> None:
    assert "GPL-3.0-or-later" in README


def test_readme_has_no_stale_pre_publication_claims() -> None:
    for stale in ("not published", "none declared yet", "private methodology"):
        assert stale not in README_LOWER, f"stale claim survived in README: {stale!r}"


def test_readme_relative_links_resolve() -> None:
    linked = re.findall(r"\[[^\]]+\]\(([^)]+)\)", README)
    assert linked, "README declares no links at all; the link check is vacuous"
    checked = 0
    for target in linked:
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue  # pure in-page anchor
        resolved = (REPO_ROOT / path_part).resolve()
        assert resolved.exists(), f"README links to a missing file: {target!r} -> {resolved}"
        checked += 1
    assert checked > 0, "README declares only http links; the relative-link check is vacuous"


def test_readme_test_count_matches_pytest_collection() -> None:
    match = re.search(r"pytest suite \((\d+) tests\)", README)
    assert match, (
        "README no longer states a pytest test count. If the numeric claim was "
        "dropped deliberately, replace this pinning test with one asserting no "
        "stale count remains; if it was dropped by accident, restore it."
    )
    claimed = int(match.group(1))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    collected_match = re.search(r"(\d+) tests collected", result.stdout)
    assert collected_match, (
        f"could not parse pytest collection output (tail):\n{result.stdout[-2000:]}"
    )
    collected = int(collected_match.group(1))
    assert claimed == collected, (
        f"README claims {claimed} tests but pytest actually collects {collected}; "
        "update the README count (the suite grew or shrank)"
    )


def test_gitignore_covers_local_only_paths() -> None:
    for rule in (".agents/", ".claude/", ".codegraph/", "skills-lock.json", "local.cmd"):
        assert rule in GITIGNORE, f".gitignore is missing the local-only rule {rule!r}"

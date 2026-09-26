"""Contract tests for the Blender native-extension packaging.

Gates the packaging contract: the manifest in packaging/blender_manifest.toml
must agree with bl_info in addon/__init__.py, staging must produce the layout
Blender's own extension validator requires (manifest and package modules side
by side), and no machine-specific paths may leak into shipped files.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from tools.build_extension import stage_extension

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "packaging" / "blender_manifest.toml"
ADDON_INIT = REPO_ROOT / "addon" / "__init__.py"
EXPECTED_LICENSE = "SPDX:GPL-3.0-or-later"

# Matches drive-absolute Windows paths such as C:\... or D:/... anywhere in a file.
DRIVE_ABSOLUTE_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/]")


def _load_bl_info() -> dict:
    """Extract bl_info from addon/__init__.py without importing bpy."""
    tree = ast.parse(ADDON_INIT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("bl_info not found in addon/__init__.py")


def _load_manifest() -> dict:
    with MANIFEST_PATH.open("rb") as fh:
        return tomllib.load(fh)


def test_manifest_version_matches_bl_info() -> None:
    bl_info = _load_bl_info()
    major, minor, patch = bl_info["version"]
    assert _load_manifest()["version"] == f"{major}.{minor}.{patch}"


def test_manifest_name_matches_bl_info() -> None:
    assert _load_manifest()["name"] == _load_bl_info()["name"]


def test_manifest_license_is_gpl3_or_later() -> None:
    license_field = _load_manifest()["license"]
    licenses = license_field if isinstance(license_field, list) else [license_field]
    assert EXPECTED_LICENSE in licenses


def test_stage_extension_produces_validator_layout(tmp_path: Path) -> None:
    # Blender's validator requires __init__.py directly beside the manifest.
    written = stage_extension(tmp_path)
    assert (tmp_path / "blender_manifest.toml").is_file()
    assert (tmp_path / "__init__.py").is_file()
    assert written  # every staged file is reported


def test_staged_package_has_no_absolute_addon_imports(tmp_path: Path) -> None:
    stage_extension(tmp_path)
    staged = sorted(p for p in tmp_path.rglob("*.py"))
    assert staged, "staging produced no python files"
    offenders = [
        p
        for p in staged
        if re.search(r"^\s*(import addon|from addon\b)", p.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert offenders == []


def test_dist_is_gitignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "dist"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert result.returncode == 0, "dist/ is not gitignored"


@pytest.mark.parametrize(
    "shipped_file",
    [MANIFEST_PATH, REPO_ROOT / "tools" / "build_extension.py"],
    ids=["manifest", "build_script"],
)
def test_no_machine_specific_paths(shipped_file: Path) -> None:
    text = shipped_file.read_text(encoding="utf-8")
    match = DRIVE_ABSOLUTE_PATH_RE.search(text)
    assert match is None, f"drive-absolute path in {shipped_file.name}: {match!r}"

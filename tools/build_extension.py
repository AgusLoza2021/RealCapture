"""Stage (and optionally validate) the RealCapture Blender native extension.

Blender 4.2+ native extensions require ``blender_manifest.toml`` at the root of
the extension source tree, directly beside the add-on modules: Blender's own
``--command extension validate`` rejects a manifest whose directory does not
contain ``__init__.py`` (a nested ``<id>/`` package directory is NOT accepted
as the source layout; ``<id>/`` is the directory name Blender creates on
install). Staging therefore copies the repository's ``addon/`` package FLAT
into the destination, next to the manifest.

The repository's ``addon/`` directory is never moved or mutated: staging makes
a copy, so dev-mode use of ``addon/`` keeps working.

Stdlib only; no Blender installation is required to stage.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_NAME = "blender_manifest.toml"
SOURCE_MANIFEST = REPO_ROOT / "packaging" / MANIFEST_NAME
ADDON_DIR = REPO_ROOT / "addon"
# Local caches and compiled artifacts are never part of a staged extension.
EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc"}


def manifest_id() -> str:
    """Return the extension id declared in packaging/blender_manifest.toml."""
    with SOURCE_MANIFEST.open("rb") as fh:
        data = tomllib.load(fh)
    return str(data["id"])


def stage_extension(dest: Path | str) -> list[Path]:
    """Stage the extension layout under *dest* and return the written paths.

    Writes ``dest/blender_manifest.toml`` plus a flat copy of the ``addon/``
    package (manifest and modules side by side, as Blender's validator
    requires). Existing files in *dest* are overwritten; nothing under the
    repository's ``addon/`` is touched.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    manifest_dest = dest / MANIFEST_NAME
    shutil.copyfile(SOURCE_MANIFEST, manifest_dest)
    written.append(manifest_dest)

    for src in sorted(ADDON_DIR.rglob("*")):
        rel = src.relative_to(ADDON_DIR)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if src.is_dir():
            if src.suffix in EXCLUDED_SUFFIXES:
                continue
            (dest / rel).mkdir(parents=True, exist_ok=True)
            continue
        if src.suffix in EXCLUDED_SUFFIXES:
            continue
        target = dest / rel
        shutil.copyfile(src, target)
        written.append(target)

    return written


def run_blender_extension_command(
    blender_exe: Path | str, *args: str
) -> subprocess.CompletedProcess[str]:
    """Run ``blender --command extension <args...>`` and return the result."""
    cmd = [str(blender_exe), "--command", "extension", *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def validate_staged(staged_dir: Path | str, blender_exe: Path | str) -> subprocess.CompletedProcess[str]:
    """Run Blender's extension validator on a staged tree.

    Uses ``--valid-tags=""`` so tag validation never blocks packaging checks;
    the manifest's own tags are still emitted for the extensions platform.
    """
    return run_blender_extension_command(
        blender_exe,
        "validate",
        "--valid-tags=",
        str(staged_dir),
    )


def build_staged(
    staged_dir: Path | str, out_dir: Path | str, blender_exe: Path | str
) -> subprocess.CompletedProcess[str]:
    """Run Blender's extension builder on a staged tree, zips into *out_dir*."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return run_blender_extension_command(
        blender_exe,
        "build",
        "--source-dir",
        str(staged_dir),
        "--output-dir",
        str(out_dir),
        "--valid-tags=",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dest",
        type=Path,
        default=REPO_ROOT / "dist",
        help="staging directory (default: <repo>/dist)",
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=None,
        help="blender executable for --validate/--build (default: 'blender' on PATH)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="run Blender's extension validator on the staged tree",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="run Blender's extension builder after staging",
    )
    args = parser.parse_args(argv)

    if (args.validate or args.build) and args.blender is None:
        which = shutil.which("blender")
        if which is None:
            parser.error(
                "--validate/--build need Blender: pass --blender <path> "
                "or put 'blender' on PATH"
            )
        args.blender = Path(which)
    written = stage_extension(args.dest)
    print(f"Staged extension into {args.dest.resolve()}:")
    for path in written:
        print(f"  wrote {path.relative_to(args.dest)}")

    if args.validate:
        result = validate_staged(args.dest, args.blender)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        print(f"validate exit code: {result.returncode}")
        if result.returncode != 0:
            return result.returncode

    if args.build:
        result = build_staged(args.dest, args.dest, args.blender)
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        print(f"build exit code: {result.returncode}")
        for zip_path in sorted(args.dest.glob("*.zip")):
            print(f"  built {zip_path}")
        if result.returncode != 0:
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

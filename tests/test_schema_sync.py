"""Guard: the vendored addon schema must stay byte-identical to the backend one."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_SCHEMA = REPO_ROOT / "backend" / "common" / "packets.py"
ADDON_SCHEMA = REPO_ROOT / "addon" / "schema.py"


def test_mirrored_schema_files_are_identical():
    assert BACKEND_SCHEMA.exists() and ADDON_SCHEMA.exists()
    assert BACKEND_SCHEMA.read_bytes() == ADDON_SCHEMA.read_bytes(), (
        "backend/common/packets.py and addon/schema.py diverged. "
        "They are an intentional mirror; update both together."
    )

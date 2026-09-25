"""Name standardization and side extraction for rig matching.

Inspired by the auto-detection workflows common in mocap-retargeting addons
(see docs/research/rig-mapping-workflow-landscape.md); this implementation is
original. The goal: "Jaw_Open", "jawOpen", "jaw-open" and "jaw_open" must all
resolve to the same base, and side markers must be extracted into a canonical
tag so alias matching only needs side-neutral stems.
"""

from __future__ import annotations

import re

_COMMON_PREFIXES = (
    "valvebiped_",
    "bip01_",
    "bip001_",
    "bip_",
    "mixamorig",
    "def_",
    "def-",
    "org_",
    "mch_",
    "ctl_",
    "rig_",
)

_COMMON_SUFFIXES = (
    "_jnt",
    "_joint",
    "_bone",
    "_ctrl",
    "_control",
    "_s0",
)

_SEPARATORS_RE = re.compile(r"[\s:\-\.]+")
_MULTISPACE_RE = re.compile(r"_+")

# Side preceded by a separator: "arm_r", "eye.L", "hand-left", "left_hand".
_SIDE_SUFFIX_RE = re.compile(r"(?:[._\-]|^)(l|r|left|right)$", re.IGNORECASE)
_SIDE_PREFIX_RE = re.compile(r"^(l|r|left|right)(?:[._\-]|$)", re.IGNORECASE)
# CamelCase trailing side: "jawL", "EyeR", "handLeft".
_SIDE_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(L|R|Left|Right)$")


def _strip_affixes(name: str) -> str:
    """Strip common prefixes/suffixes, preserving the case of the remainder."""
    cleaned = name.strip()
    changed = True
    while changed:
        changed = False
        for prefix in _COMMON_PREFIXES:
            if cleaned.lower().startswith(prefix) and len(cleaned) > len(prefix):
                cleaned = cleaned[len(prefix):]
                changed = True
        for suffix in _COMMON_SUFFIXES:
            if cleaned.lower().endswith(suffix) and len(cleaned) > len(suffix):
                cleaned = cleaned[: -len(suffix)]
                changed = True
    return cleaned


def standardize(name: str) -> str:
    """Lowercase, strip common prefixes/suffixes, normalize separators.

    Returns the standardized base WITHOUT side resolution: ``Jaw_Open`` and
    ``jaw.open`` both become ``jaw_open``; sides are handled by
    :func:`split_side` on the *original* name (standardizing first can eat a
    lone ``l``/``r`` segment).
    """
    cleaned = _strip_affixes(name).lower()
    cleaned = _SEPARATORS_RE.sub("_", cleaned)
    cleaned = _MULTISPACE_RE.sub("_", cleaned).strip("_")
    return cleaned


def split_side(name: str) -> tuple[str, str | None]:
    """Split a control name into (standardized_base, side) with side in {"L","R",None}.

    Handles the common conventions: ``.L``/``_R`` suffixes (Rigify, Unity),
    ``L_``/``R_`` prefixes, ``left``/``right`` words, and CamelCase trailing
    sides such as ``jawL``. A lone ``l``/``r`` only counts as a side when a
    separator precedes it, so ``jaw`` never becomes sided.
    """
    base = _strip_affixes(name)

    for regex in (_SIDE_SUFFIX_RE, _SIDE_CAMEL_RE):
        match = regex.search(base)
        if match:
            side = _normalize_side(match.group(1))
            if side:
                return standardize(base[: match.start()]), side

    match = _SIDE_PREFIX_RE.match(base)
    if match:
        side = _normalize_side(match.group(1))
        if side:
            return standardize(base[match.end():]), side

    return standardize(base), None


def _normalize_side(token: str) -> str | None:
    token = token.lower()
    if token in ("l", "left"):
        return "L"
    if token in ("r", "right"):
        return "R"
    return None

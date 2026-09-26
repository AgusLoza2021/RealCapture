"""Pure head-bone selection and rest-deformation gate.

This module must NEVER import bpy: it is unit-tested without Blender
(tests/test_headbone_gate.py). It encodes the geometric rule that stopped
defect T9, where a MakeHuman/MPFB2 character's bone named 'head' sits at
chest height (z = 0.697 m on a 1.667 m character) while the real skull is
held by FACS muscle bones. Parenting face-point empties to such a bone
tears the mesh apart before a single capture packet arrives.

Selection rule (choose_head_bone)
---------------------------------
1. A candidate is only name-eligible when ``name.lower()`` starts with
   ``"head"`` (``extra_head``, ``HEAD``, ``head_01`` qualify; ``neck``,
   ``spine01``, ``HeadTop_Nub`` never do).
2. A candidate is only position-eligible when its representative height
   ``z`` is at or above the mesh's vertical midpoint **plus a margin** of
   ``HEAD_MIN_MARGIN_FRACTION`` (5%) of the mesh height. A bone merely at
   the midpoint is not a safe head anchor, so a meaningful margin above
   the midpoint is required.
3. Among the eligible candidates the highest one wins. When none
   qualifies the function returns ``None`` and the caller must fall back
   to a shape-keys-only bind instead of guessing.

The ``z`` passed per candidate is the caller's representative height for
the bone; the Blender layer (addon/binding.py) feeds the bone's highest
world-space point (max of head and tail joint z), so a bone only counts
as a head if its extent actually reaches into the upper part of the mesh.

Gate selectability (is_gate_measurable)
---------------------------------------
The rest gate must never depend on state written during the bind, because
the first version did: it selected meshes by the shape-key marker that is
written AFTER the gate runs, so it measured nothing, never fired, and the
bind still reported full success over a mesh torn by 0.8211 m. The
selectable-mesh rule is therefore pure and lives here, tested.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import inf

HEAD_NAME_PREFIX = "head"

#: Fraction of the mesh height a head candidate must rise above the mesh's
#: vertical midpoint before it is accepted (5% of a 1.667 m character is
#: ~8 cm; the measured MPFB2 'head' stub is ~14 cm BELOW the midpoint).
HEAD_MIN_MARGIN_FRACTION = 0.05

#: At-rest displacement ceiling in metres. A bind whose meshes move more
#: than this with every shape key at 0 is clearly broken (the measured T9
#: damage was 0.8211 m); a legitimate rig with roughly-placed anchors stays
#: far below it.
REST_GATE_THRESHOLD = 0.25


def _is_name_eligible(name: object) -> bool:
    """True when the bone name starts with the head prefix (case-insensitive)."""
    return isinstance(name, str) and name.lower().startswith(HEAD_NAME_PREFIX)


def _acceptance_floor(mesh_z_min: float, mesh_z_max: float) -> float | None:
    """Lowest acceptable z for a head bone, or None when the mesh bounds
    are degenerate (no mesh, zero-height bounds)."""
    height = mesh_z_max - mesh_z_min
    if height <= 0.0:
        return None
    midpoint = mesh_z_min + height / 2.0
    return midpoint + HEAD_MIN_MARGIN_FRACTION * height


def choose_head_bone(candidates: Iterable[tuple[str, float]],
                     mesh_z_min: float, mesh_z_max: float) -> str | None:
    """Return the highest acceptable head bone, or None when none qualifies.

    See the module docstring for the exact rule. A torso bone named 'head'
    (the defect-T9 shape) returns None.
    """
    floor = _acceptance_floor(mesh_z_min, mesh_z_max)
    if floor is None:
        return None
    best_name: str | None = None
    best_z = -inf
    for entry in candidates:
        try:
            name, z = entry
        except (TypeError, ValueError):
            continue  # malformed candidate: never a reason to guess
        if not _is_name_eligible(name):
            continue
        if z < floor:
            continue
        if z > best_z:
            best_name, best_z = name, z
    return best_name


def highest_head_candidate(candidates: Sequence[tuple[str, float]]) -> tuple[str, float] | None:
    """Return the highest 'head*'-named candidate regardless of position.

    Used for actionable reporting when :func:`choose_head_bone` returns
    None: the caller can name the rejected bone and its height. Returns
    None when no candidate name starts with the head prefix.
    """
    best: tuple[str, float] | None = None
    for name, z in candidates:
        if not _is_name_eligible(name):
            continue
        if best is None or z > best[1]:
            best = (name, z)
    return best


def exceeds_rest_gate(max_delta: float,
                      threshold: float = REST_GATE_THRESHOLD) -> bool:
    """True when a bind's at-rest mesh displacement is clearly broken.

    Strictly greater than: a bind exactly at the ceiling is allowed, one
    over it is rejected and must be torn back down to shape-keys-only.
    """
    return max_delta > threshold


def is_gate_measurable(mesh: object) -> bool:
    """True when the rest gate is able to measure this object at all.

    This rule exists because its first version was wrong in the same way
    the gate was meant to catch: it filtered on the marker property that
    the *shape-key* bind writes, and that write happens AFTER the gate
    runs. The candidate list was therefore always empty, the worst
    displacement came back as ``None``, ``exceeds_rest_gate`` was never
    consulted, and the bind still reported 3 bones and 11 point
    transforms while tearing a real character by 0.8211 m. A check that
    cannot fail is not a check.

    The rule stated here is order-independent: an object is measurable
    when it is a MESH whose data carries shape keys including ``Basis``.
    That is exactly the face mesh the bind can deform, so the gate never
    depends on anything written during the bind itself.
    """
    if getattr(mesh, "type", None) != "MESH":
        return False
    shape_keys = getattr(getattr(mesh, "data", None), "shape_keys", None)
    key_blocks = getattr(shape_keys, "key_blocks", None)
    if key_blocks is None:
        return False
    try:
        return "Basis" in key_blocks
    except TypeError:  # a key_blocks stand-in that is not a container
        return False

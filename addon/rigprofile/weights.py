"""Pure weight-zone operations for skin weights.

This module must NEVER import bpy: it is unit-tested without Blender
(tests/test_rigprofile_weights.py). It is the pure core of feature unit R5a
(odd/tasks/modular-rig-targets.md): the four zone operations the field's
weight editors converge on (add, subtract, scale, set), per-vertex
normalization and an influence limit, expressed over plain mappings so the
Blender layer only has to read and write vertex-group data around it.

The refusal rules are the point of this unit. This project already paid
once for a check that reported success over nothing (the vacuous rest gate
measured no mesh and the bind still reported success over a mesh torn by
0.8211 m), so every invalid input here fails loudly with
:class:`WeightZoneError` instead of quietly doing nothing: an empty zone,
an unknown operation, a non-finite weight, a non-integer influence limit.
Nothing is skipped or coerced silently.

Zones (WeightZone)
------------------
A zone is a named set of vertex indices. ``vertices`` is stored sorted
ascending whatever the input order, so a zone is comparable and
serialisable. An empty selection is refused at construction: operating on
nothing must never read back as a successful edit.

Edits (apply_zone_edit)
-----------------------
The four operations apply per zone vertex and the result is clamped to
``[WEIGHT_MIN, WEIGHT_MAX]``. A zone vertex absent from the input mapping
enters at ``0.0`` and appears in the result; a vertex outside the zone is
copied through clamped. The input mapping is never mutated and the result
is a new dict.

Normalization (normalize_vertex)
--------------------------------
One vertex's weights across its vertex groups, rescaled to sum to 1.0. The
all-zero vertex stays all-zero: dividing by zero would produce NaN and
silently destroy every group on the vertex.

Influence limit (limit_influences)
----------------------------------
Keeps the ``max_influences`` largest influences (default 4, because VRM and
glTF cap skin influences at four) with a deterministic tie-break:
descending weight, then ascending group name. Unlike Blender's own
"Limit Total" this function does NOT renormalize by default: with
``normalize=False`` the kept subset keeps its raw values (a subset sum
below 1.0 is expected), with ``normalize=True`` the kept subset is
renormalized through :func:`normalize_vertex`.

Change reporting (changed_vertices)
-----------------------------------
Sorted vertex indices whose weight differs between two mappings, exact
float comparison, a missing key read as ``0.0``. The editing surface
reports what it actually changed instead of asserting success.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

WEIGHT_MIN = 0.0
WEIGHT_MAX = 1.0

#: The operations the field's weight editors converge on
#: (add / subtract / scale / set), applied per zone vertex.
ZONE_OPS = ("add", "subtract", "scale", "set")


class WeightZoneError(ValueError):
    """Raised when a weight-zone operation is refused instead of guessed."""


@dataclass(frozen=True)
class WeightZone:
    """A named region of the mesh: a zone name and its vertex indices.

    Construction refuses an empty or whitespace-only name, an empty
    selection, a negative index and a duplicate index, and stores the
    indices sorted ascending whatever the input order.
    """

    name: str
    vertices: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise WeightZoneError(
                f"zone name must be a non-empty string, got {self.name!r}")
        if not isinstance(self.vertices, tuple):
            raise WeightZoneError(
                f"zone {self.name!r}: vertices must be a tuple of ints, "
                f"got {type(self.vertices).__name__}")
        seen: set[int] = set()
        for vertex in self.vertices:
            if isinstance(vertex, bool) or not isinstance(vertex, int):
                raise WeightZoneError(
                    f"zone {self.name!r}: vertex index must be an int, "
                    f"got {vertex!r}")
            if vertex < 0:
                raise WeightZoneError(
                    f"zone {self.name!r}: negative vertex index {vertex}")
            if vertex in seen:
                raise WeightZoneError(
                    f"zone {self.name!r}: duplicate vertex index {vertex}")
            seen.add(vertex)
        if not self.vertices:
            raise WeightZoneError(
                f"zone {self.name!r}: empty selection (operating on nothing "
                f"is refused, never a silent no-op)")
        object.__setattr__(self, "vertices", tuple(sorted(self.vertices)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "vertices": list(self.vertices)}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WeightZone":
        """Rebuild a zone from its :meth:`to_dict` form, revalidating
        every rule through the constructor."""
        if not isinstance(data, dict):
            raise WeightZoneError("zone document must be a JSON object")
        name = data.get("name")
        vertices = data.get("vertices")
        if not isinstance(name, str):
            raise WeightZoneError(
                f"zone document: 'name' must be a string, got {name!r}")
        if not isinstance(vertices, list):
            raise WeightZoneError(
                f"zone document: 'vertices' must be a list, got {vertices!r}")
        return WeightZone(name=name, vertices=tuple(vertices))


def _finite_weight(source: str, key: object, value: object) -> float:
    """Validate one weight value: a finite number, refusing bool.

    Returns the value as float. Raises WeightZoneError naming the source
    and key for anything that is not a real finite number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeightZoneError(
            f"{source} {key!r}: weight must be a number, got {value!r}")
    weight = float(value)
    if not math.isfinite(weight):
        raise WeightZoneError(
            f"{source} {key!r}: non-finite weight {value!r}")
    return weight


def _validated_vertex_weights(weights: dict[int, float], label: str) -> None:
    """Refuse non-int vertex indices and non-finite weights in a mapping."""
    for key, weight in weights.items():
        if isinstance(key, bool) or not isinstance(key, int):
            raise WeightZoneError(
                f"{label}: vertex index must be an int, got {key!r}")
        _finite_weight(f"{label} weight for vertex", key, weight)


def _validated_group_weights(weights_by_group: dict[str, float]) -> dict[str, float]:
    """Refuse non-string group names and non-finite weights, return floats."""
    validated: dict[str, float] = {}
    for group, weight in weights_by_group.items():
        if not isinstance(group, str):
            raise WeightZoneError(
                f"vertex-group name must be a string, got {group!r}")
        validated[group] = _finite_weight("vertex group", group, weight)
    return validated


def apply_zone_edit(weights: dict[int, float], zone: WeightZone, op: str,
                    value: float) -> dict[int, float]:
    """Apply one zone operation over ``zone.vertices`` and return a new dict.

    ``add`` -> ``w + value``, ``subtract`` -> ``w - value``,
    ``scale`` -> ``w * value``, ``set`` -> ``value``; every result (zone
    and pass-through alike) is clamped to ``[WEIGHT_MIN, WEIGHT_MAX]``.
    A zone vertex absent from ``weights`` enters at ``0.0`` and appears in
    the result; a vertex outside the zone is copied through clamped. The
    input mapping is never mutated.

    Raises WeightZoneError for an unknown ``op`` (naming it), a non-finite
    ``value`` and a non-finite weight already present in ``weights``.
    """
    if not isinstance(zone, WeightZone):
        raise WeightZoneError(
            f"zone must be a WeightZone, got {type(zone).__name__}")
    if op not in ZONE_OPS:
        raise WeightZoneError(
            f"unknown zone operation {op!r}; expected one of {ZONE_OPS}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeightZoneError(
            f"operation {op!r}: value must be a finite number, got {value!r}")
    if not math.isfinite(value):
        raise WeightZoneError(
            f"operation {op!r}: non-finite value {value!r}")
    _validated_vertex_weights(weights, "weights")

    result: dict[int, float] = {}
    zone_vertices = set(zone.vertices)
    for vertex in zone.vertices:
        w = float(weights.get(vertex, 0.0))
        if op == "add":
            new = w + value
        elif op == "subtract":
            new = w - value
        elif op == "scale":
            new = w * value
        else:  # "set"
            new = value
        result[vertex] = min(max(new, WEIGHT_MIN), WEIGHT_MAX)
    for vertex, weight in weights.items():
        if vertex in zone_vertices:
            continue
        result[vertex] = min(max(float(weight), WEIGHT_MIN), WEIGHT_MAX)
    return result


def normalize_vertex(weights_by_group: dict[str, float]) -> dict[str, float]:
    """Rescale one vertex's weights across its groups to sum to 1.0.

    Returns a new dict; the input is never mutated. An all-zero vertex is
    returned unchanged (all zeros) instead of being divided by zero; an
    empty mapping returns an empty mapping. Negative and non-finite
    weights raise WeightZoneError.
    """
    validated = _validated_group_weights(weights_by_group)
    if not validated:
        return {}
    total = sum(validated.values())
    for group, weight in validated.items():
        if weight < 0.0:
            raise WeightZoneError(
                f"vertex group {group!r}: negative weight {weight!r}")
    if total == 0.0:
        return dict(validated)
    return {group: weight / total for group, weight in validated.items()}


def limit_influences(weights_by_group: dict[str, float],
                     max_influences: int = 4, *,
                     normalize: bool = False) -> dict[str, float]:
    """Keep the ``max_influences`` largest influences of one vertex.

    The tie-break is deterministic: descending weight, then ascending
    group name. With ``normalize=False`` (the default) the kept subset
    keeps its raw values — Blender's own "Limit Total" behaves this way
    and does NOT renormalize; with ``normalize=True`` the kept subset is
    renormalized through :func:`normalize_vertex`. Fewer influences than
    the limit returns an equal copy. The default cap is 4 because VRM and
    glTF cap skin influences at four.

    Raises WeightZoneError when ``max_influences`` is not a real int
    (``bool`` is refused too) or is below 1, for non-finite weights, and
    for non-string group names.
    """
    if isinstance(max_influences, bool) or not isinstance(max_influences, int):
        raise WeightZoneError(
            f"max_influences must be an int, got {max_influences!r}")
    if max_influences < 1:
        raise WeightZoneError(
            f"max_influences must be >= 1, got {max_influences}")
    if not isinstance(normalize, bool):
        raise WeightZoneError(
            f"normalize must be a bool, got {normalize!r}")
    validated = _validated_group_weights(weights_by_group)
    ranked = sorted(validated.items(), key=lambda item: (-item[1], item[0]))
    kept = dict(ranked[:max_influences])
    if normalize:
        return normalize_vertex(kept)
    return kept


def changed_vertices(before: dict[int, float],
                     after: dict[int, float]) -> tuple[int, ...]:
    """Sorted vertex indices whose weight differs between two mappings.

    Exact float comparison, a missing key read as ``0.0``: this is how the
    editing surface reports what it actually changed instead of asserting
    success. Raises WeightZoneError for non-int indices or non-finite
    weights in either mapping.
    """
    _validated_vertex_weights(before, "before")
    _validated_vertex_weights(after, "after")
    changed = [vertex for vertex in set(before) | set(after)
               if before.get(vertex, 0.0) != after.get(vertex, 0.0)]
    return tuple(sorted(changed))

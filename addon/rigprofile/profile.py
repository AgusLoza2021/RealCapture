"""Versioned RigProfile JSON schema: the saved output of the setup wizard.

A RigProfile records how one rig connects to RealCapture: which FPD points
exist and how they are driven, which shape keys bind to which channels, and
which bones follow which points. It is plain data — the Blender layer turns it
into empties, drivers and constraints, and this module stays importable
without bpy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

PROFILE_VERSION = 1
PROFILE_KIND = "realcapture-rig-profile"

_CONSTRAINT_KINDS = ("copy_location", "copy_rotation", "damped_track")
_AXES = ("X", "Y", "Z")


class ProfileError(ValueError):
    """Raised when a profile document is structurally invalid."""


@dataclass
class PointTransform:
    """How one FPD empty moves in response to one channel."""

    role: str                      # point role, e.g. "jaw", "eye_lid.L"
    channel: str                   # ARKit channel name
    kind: str = "location"         # "location" | "rotation"
    axis: str = "Y"
    gain: float = 1.0
    invert: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "channel": self.channel, "kind": self.kind,
                "axis": self.axis, "gain": self.gain, "invert": self.invert}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PointTransform":
        role, channel = _req_str(data, "role"), _req_str(data, "channel")
        kind = data.get("kind", "location")
        axis = data.get("axis", "Y")
        if kind not in ("location", "rotation"):
            raise ProfileError(f"point {role!r}: kind must be location|rotation")
        if axis not in _AXES:
            raise ProfileError(f"point {role!r}: axis must be one of {_AXES}")
        return PointTransform(role=role, channel=channel, kind=kind, axis=axis,
                              gain=float(data.get("gain", 1.0)),
                              invert=bool(data.get("invert", False)))


@dataclass
class ShapeKeyBinding:
    """A shape key driven directly by a channel value."""

    channel: str
    target: str                    # shape key name on the mesh
    gain: float = 1.0
    invert: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"channel": self.channel, "target": self.target,
                "gain": self.gain, "invert": self.invert}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ShapeKeyBinding":
        return ShapeKeyBinding(
            channel=_req_str(data, "channel"), target=_req_str(data, "target"),
            gain=float(data.get("gain", 1.0)), invert=bool(data.get("invert", False)))


@dataclass
class BoneBinding:
    """A pose bone following an FPD point through a native constraint."""

    point: str                     # point role whose empty is the constraint target
    target: str                    # pose bone name
    constraint: str = "copy_location"
    axes: tuple[bool, bool, bool] = (True, True, True)
    invert: tuple[bool, bool, bool] = (False, False, False)
    gain: float = 1.0
    head_tail: float = 0.0         # position along the bone for copy_location

    def to_dict(self) -> dict[str, Any]:
        return {"point": self.point, "target": self.target,
                "constraint": self.constraint, "axes": list(self.axes),
                "invert": list(self.invert), "gain": self.gain,
                "head_tail": self.head_tail}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "BoneBinding":
        constraint = data.get("constraint", "copy_location")
        if constraint not in _CONSTRAINT_KINDS:
            raise ProfileError(f"bone binding {data.get('target')!r}: unknown "
                               f"constraint kind {constraint!r}")
        axes = _triple(data.get("axes"), True)
        invert = _triple(data.get("invert"), False)
        return BoneBinding(
            point=_req_str(data, "point"), target=_req_str(data, "target"),
            constraint=constraint, axes=axes, invert=invert,
            gain=float(data.get("gain", 1.0)),
            head_tail=float(data.get("head_tail", 0.0)))


@dataclass
class RigProfile:
    """Complete, versioned mapping document for one rig."""

    name: str
    head_bone: str | None = None
    rig_kind: str = "custom"       # "rigify" | "faceit" | "vrm" | "custom"
    points: list[PointTransform] = field(default_factory=list)
    shapekey_bindings: list[ShapeKeyBinding] = field(default_factory=list)
    bone_bindings: list[BoneBinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PROFILE_VERSION,
            "kind": PROFILE_KIND,
            "name": self.name,
            "head_bone": self.head_bone,
            "rig_kind": self.rig_kind,
            "points": [p.to_dict() for p in self.points],
            "shapekey_bindings": [b.to_dict() for b in self.shapekey_bindings],
            "bone_bindings": [b.to_dict() for b in self.bone_bindings],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RigProfile":
        if not isinstance(data, dict):
            raise ProfileError("profile document must be a JSON object")
        if data.get("kind") != PROFILE_KIND:
            raise ProfileError(f"expected kind {PROFILE_KIND!r}, got {data.get('kind')!r}")
        if data.get("version") != PROFILE_VERSION:
            raise ProfileError(f"unsupported profile version {data.get('version')!r}")
        profile = RigProfile(
            name=data.get("name") or "Unnamed rig",
            head_bone=data.get("head_bone"),
            rig_kind=data.get("rig_kind", "custom"),
        )
        try:
            profile.points = [PointTransform.from_dict(p) for p in data.get("points", [])]
            profile.shapekey_bindings = [ShapeKeyBinding.from_dict(b)
                                         for b in data.get("shapekey_bindings", [])]
            profile.bone_bindings = [BoneBinding.from_dict(b)
                                     for b in data.get("bone_bindings", [])]
        except (TypeError, KeyError) as exc:
            raise ProfileError(f"malformed profile entry: {exc}") from exc
        return profile

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_json(text: str) -> "RigProfile":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProfileError(f"invalid JSON: {exc}") from exc
        return RigProfile.from_dict(data)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())

    @staticmethod
    def load(path: str) -> "RigProfile":
        with open(path, "r", encoding="utf-8") as fh:
            return RigProfile.from_json(fh.read())


def _req_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ProfileError(f"missing or empty field {key!r}")
    return value


def _triple(value: Any, default: bool) -> tuple[bool, bool, bool]:
    if value is None:
        return (default, default, default)
    if (not isinstance(value, (list, tuple))) or len(value) != 3:
        raise ProfileError("axes/invert must be a 3-element list")
    return (bool(value[0]), bool(value[1]), bool(value[2]))

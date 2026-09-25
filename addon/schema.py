"""RealCapture UDP packet schema (TDD section 4.3).

This file is mirrored byte-identically as ``backend/common/packets.py``
(capture-backend side) and ``addon/schema.py`` (Blender-addon side).
Keep them in sync; ``tests/test_schema_sync.py`` enforces it.

The packet is the public seam between the capture backend (external process)
and the Blender addon. Schema is versioned; keep this module dependency-free
so it can be vendored/tested on both sides.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict

PACKET_SCHEMA_VERSION = 1

REQUIRED_TOP_LEVEL_FIELDS = ("t", "engine", "conf", "pose", "shapes")
OPTIONAL_TOP_LEVEL_FIELDS = ("extra",)
KNOWN_TOP_LEVEL_FIELDS = frozenset(REQUIRED_TOP_LEVEL_FIELDS + OPTIONAL_TOP_LEVEL_FIELDS)

POSE_KEYS = ("rx", "ry", "rz", "tx", "ty", "tz")


class PacketValidationError(ValueError):
    """Raised when a packet dict or payload violates the schema."""


@dataclass
class Packet:
    """One facial-capture frame ready for transport."""

    t: int
    engine: str
    conf: float
    pose: Dict[str, float]
    shapes: Dict[str, float]
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "t": self.t,
            "engine": self.engine,
            "conf": self.conf,
            "pose": dict(self.pose),
            "shapes": dict(self.shapes),
        }
        if self.extra:
            data["extra"] = dict(self.extra)
        return data


def _check_float(value: Any, where: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PacketValidationError(f"{where} must be a number, got {type(value).__name__}")
    value = float(value)
    if not math.isfinite(value):
        raise PacketValidationError(f"{where} must be finite, got {value}")
    if lo is not None and value < lo:
        raise PacketValidationError(f"{where} must be >= {lo}, got {value}")
    if hi is not None and value > hi:
        raise PacketValidationError(f"{where} must be <= {hi}, got {value}")
    return value


def _check_int(value: Any, where: str, lo: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PacketValidationError(f"{where} must be an integer, got {type(value).__name__}")
    if lo is not None and value < lo:
        raise PacketValidationError(f"{where} must be >= {lo}, got {value}")
    return value


def validate_packet_dict(raw: Any) -> Dict[str, Any]:
    """Validate a packet dict in place and return it.

    Raises PacketValidationError on any schema violation.
    """
    if not isinstance(raw, dict):
        raise PacketValidationError(f"packet must be a JSON object, got {type(raw).__name__}")

    unknown = set(raw) - KNOWN_TOP_LEVEL_FIELDS
    if unknown:
        raise PacketValidationError(f"unknown packet fields: {sorted(unknown)}")

    for key in REQUIRED_TOP_LEVEL_FIELDS:
        if key not in raw:
            raise PacketValidationError(f"missing required packet field: {key}")

    _check_int(raw["t"], "t", lo=0)

    engine = raw["engine"]
    if not isinstance(engine, str) or not engine:
        raise PacketValidationError("engine must be a non-empty string")

    _check_float(raw["conf"], "conf", lo=0.0, hi=1.0)

    pose = raw["pose"]
    if not isinstance(pose, dict):
        raise PacketValidationError("pose must be an object")
    missing_pose = [key for key in POSE_KEYS if key not in pose]
    if missing_pose:
        raise PacketValidationError(f"pose missing keys: {missing_pose}")
    if set(pose) - set(POSE_KEYS):
        raise PacketValidationError(f"pose has unknown keys: {sorted(set(pose) - set(POSE_KEYS))}")
    for key in POSE_KEYS:
        _check_float(pose[key], f"pose.{key}")

    shapes = raw["shapes"]
    if not isinstance(shapes, dict):
        raise PacketValidationError("shapes must be an object")
    for name, value in shapes.items():
        if not isinstance(name, str) or not name:
            raise PacketValidationError("shapes keys must be non-empty strings")
        _check_float(value, f"shapes.{name}", lo=0.0, hi=1.0)

    if "extra" in raw and not isinstance(raw["extra"], dict):
        raise PacketValidationError("extra must be an object")

    return raw


def decode_packet(data: bytes) -> Packet:
    """Decode and validate a UTF-8 JSON UDP payload into a Packet."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PacketValidationError(f"payload is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PacketValidationError(f"payload is not valid JSON: {exc}") from exc

    validated = validate_packet_dict(raw)
    return Packet(
        t=validated["t"],
        engine=validated["engine"],
        conf=validated["conf"],
        pose={key: float(validated["pose"][key]) for key in POSE_KEYS},
        shapes={name: float(value) for name, value in validated["shapes"].items()},
        extra=dict(validated.get("extra", {})),
    )


def encode_packet(
    t: int,
    engine: str,
    conf: float,
    pose: Dict[str, float],
    shapes: Dict[str, float],
    extra: Dict[str, Any] | None = None,
) -> bytes:
    """Build, validate, and serialize one packet to UTF-8 JSON bytes."""
    packet = Packet(t=t, engine=engine, conf=conf, pose=pose, shapes=shapes, extra=extra or {})
    return json.dumps(packet.to_dict(), separators=(",", ":")).encode("utf-8")

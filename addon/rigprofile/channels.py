"""Canonical channel vocabulary and Face Point Driver (FPD) point set.

The channel set is the ARKit-52 vocabulary, which is the de-facto interchange
standard for facial capture (used by our packet schema consumers, VRM presets,
and most universal rigs). Point roles are the canonical Face Point Driver
empties the connector creates and drives; rig controls then follow them via
native Blender constraints.

This module is pure data: no bpy imports.
"""

from __future__ import annotations

ARKitChannel = str

ARKIT_CHANNELS: tuple[ARKitChannel, ...] = (
    # Eyes
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft",
    "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft",
    "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight",
    "eyeLookUpRight", "eyeSquintRight", "eyeWideRight",
    # Jaw
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    # Mouth
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft",
    "mouthFrownRight", "mouthFunnel", "mouthLeft", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight", "mouthPucker",
    "mouthRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower",
    "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight",
    # Nose
    "noseSneerLeft", "noseSneerRight",
    # Cheeks
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    # Brows
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft",
    "browOuterUpRight",
    # Tongue
    "tongueOut",
)
assert len(ARKIT_CHANNELS) == 52

SIDED_CHANNELS = frozenset(c for c in ARKIT_CHANNELS if c.endswith(("Left", "Right")))


class PointRole:
    """Canonical FPD empty roles. Side-suffixed roles appear as <role>.L/.R."""

    JAW = "jaw"
    EYE = "eye"            # gaze pivot (L/R)
    EYE_LID = "eye_lid"    # blink follower (L/R)
    BROW = "brow"          # (L/R)
    MOUTH_CORNER = "mouth_corner"  # (L/R)
    LIP_TOP = "lip_top"
    LIP_BOTTOM = "lip_bottom"
    CHEEK = "cheek"        # (L/R)
    BROW_INNER = "brow_inner"


def point_roles() -> tuple[str, ...]:
    """All canonical point roles, including explicit side variants."""
    sided = (PointRole.EYE, PointRole.EYE_LID, PointRole.BROW,
             PointRole.MOUTH_CORNER, PointRole.CHEEK)
    single = (PointRole.JAW, PointRole.LIP_TOP, PointRole.LIP_BOTTOM,
              PointRole.BROW_INNER)
    return tuple(f"{role}.{side}" for role in sided for side in ("L", "R")) + single


def channel_side(channel: ARKitChannel) -> str | None:
    """Return "L"/"R" for sided ARKit channels, else None."""
    if channel.endswith("Left"):
        return "L"
    if channel.endswith("Right"):
        return "R"
    return None


def channel_base(channel: ARKitChannel) -> str:
    """Side-neutral base of a channel: ``eyeBlinkLeft`` -> ``eyeblink``."""
    side = channel_side(channel)
    if side:
        return standardize_channel(channel[: -len("Left" if side == "L" else "Right")])
    return standardize_channel(channel)


def standardize_channel(channel: ARKitChannel) -> str:
    """CamelCase ARKit name to snake-ish comparison key: ``eyeBlink`` -> ``eyeblink``."""
    return channel.lower()

"""Default FPD point transforms per role — pure data, no bpy.

Each face point can be driven by MULTIPLE channel transforms, accumulated
additively (gaze needs X from look-in/out and Z from look-up/down). Gains are
starting values in head-bone local space; artists adjust them in the profile
JSON or the empty transforms. Locations are meters, rotations radians.
"""

from __future__ import annotations

from .channels import PointRole
from .profile import PointTransform

# (role_base, channel, kind, axis, gain) — side resolved per sided channel/role.
_DEFAULTS: tuple[tuple[str, str, str, str, float], ...] = (
    # Jaw: chin drops down/back as the mouth opens.
    (PointRole.JAW, "jawOpen", "location", "Z", -0.05),
    (PointRole.JAW, "jawLeft", "location", "X", 0.02),
    (PointRole.JAW, "jawRight", "location", "X", -0.02),
    # Eyelids: lids move down to close.
    (PointRole.EYE_LID, "eyeBlink", "location", "Z", -0.012),
    (PointRole.EYE_LID, "eyeWide", "location", "Z", 0.004),
    (PointRole.EYE_LID, "eyeSquint", "location", "Z", -0.003),
    # Gaze: eyeball pivot moves within the socket.
    (PointRole.EYE, "eyeLookOut", "location", "X", 0.006),
    (PointRole.EYE, "eyeLookIn", "location", "X", -0.006),
    (PointRole.EYE, "eyeLookUp", "location", "Z", 0.004),
    (PointRole.EYE, "eyeLookDown", "location", "Z", -0.004),
    # Brows raise/lower.
    (PointRole.BROW, "browOuterUp", "location", "Z", 0.02),
    (PointRole.BROW, "browDown", "location", "Z", -0.02),
    (PointRole.BROW, "browInnerUp", "location", "Z", 0.015),
    # Mouth corners: smile pulls up/out, frown down.
    (PointRole.MOUTH_CORNER, "mouthSmile", "location", "Z", 0.012),
    (PointRole.MOUTH_CORNER, "mouthSmile", "location", "Y", 0.008),
    (PointRole.MOUTH_CORNER, "mouthFrown", "location", "Z", -0.010),
    (PointRole.MOUTH_CORNER, "mouthStretch", "location", "X", 0.008),
    # Lips.
    (PointRole.LIP_TOP, "mouthUpperUp", "location", "Z", 0.010),
    (PointRole.LIP_TOP, "mouthFunnel", "location", "Y", 0.012),
    (PointRole.LIP_BOTTOM, "mouthLowerDown", "location", "Z", -0.012),
    (PointRole.LIP_BOTTOM, "mouthFunnel", "location", "Y", 0.012),
    # Cheeks.
    (PointRole.CHEEK, "cheekSquint", "location", "Z", 0.008),
    (PointRole.CHEEK, "cheekPuff", "location", "Y", 0.015),
)


def default_point_transforms(channel_catalog: set[str] | None = None) -> list[PointTransform]:
    """Build the default point transform list.

    ``channel_catalog`` (optional) restricts output to channels that exist in
    the capture stream. Sided roles prefer their sided channel (brow.L +
    browOuterUpLeft) and fall back to the unsided channel (brow.L +
    browInnerUp), which both sides then share.
    """

    def have(channel: str) -> bool:
        return channel_catalog is None or channel in channel_catalog

    out: list[PointTransform] = []
    for role_base, stem, kind, axis, gain in _DEFAULTS:
        for role in _roles_for(role_base):
            if role.endswith(".L"):
                candidates = (stem + "Left", stem)
            elif role.endswith(".R"):
                candidates = (stem + "Right", stem)
            else:
                candidates = (stem,)
            channel = next((c for c in candidates if have(c)), None)
            if channel is None:
                continue
            out.append(PointTransform(role=role, channel=channel, kind=kind,
                                      axis=axis, gain=gain))
    return out


def _roles_for(role_base: str) -> tuple[str, ...]:
    """Expand a role base to its concrete roles, dropping missing sides."""
    if role_base in (PointRole.JAW, PointRole.LIP_TOP, PointRole.LIP_BOTTOM,
                     PointRole.BROW_INNER):
        return (role_base,)
    return (f"{role_base}.L", f"{role_base}.R")

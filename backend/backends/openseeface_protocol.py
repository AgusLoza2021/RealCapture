"""OpenSeeFace (facetracker) UDP binary protocol parser.

Reverse-engineered and cross-checked against upstream sources (BSD-2-Clause,
emilianavt/OpenSeeFace): the packing order in ``facetracker.py`` and the
parsing in ``Unity/OpenSee.cs``.

Per-face wire format (little-endian, ``<``), in order:

====  ======  =========================================================
size  type    field
====  ======  =========================================================
8     double  tracker timestamp (time.time() seconds)
4     int32   face id
8     2xf32   camera resolution (width, height)
4     float   right eye openness (1 = open)
4     float   left eye openness (1 = open)
1     uint8   success flag (got 3D points)
4     float   3D fitting error
16    4xf32   quaternion (x, y, z, w)
12    3xf32   euler angles (degrees)
12    3xf32   translation
272   68xf32  per-landmark confidence
544   68x2f32 2D landmark points (packed y, x)
840   70x3f32 3D points (packed x, -y, -z)
56    14xf32  expression features (order: FEATURES)
====  ======  =========================================================

Total: 1785 bytes per face. One datagram may contain several faces back to
back (OpenSee.cs iterates ``offset += packetFrameSize``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

OSF_FACE_SIZE = 1785
OSF_N_POINTS = 68
OSF_N_POINTS_3D = 70
OSF_N_FEATURES = 14

OSF_FEATURE_NAMES = (
    "eye_l",
    "eye_r",
    "eyebrow_steepness_l",
    "eyebrow_updown_l",
    "eyebrow_quirk_l",
    "eyebrow_steepness_r",
    "eyebrow_updown_r",
    "eyebrow_quirk_r",
    "mouth_corner_updown_l",
    "mouth_corner_inout_l",
    "mouth_corner_updown_r",
    "mouth_corner_inout_r",
    "mouth_open",
    "mouth_wide",
)


class OsfPacketError(ValueError):
    """Raised when a datagram does not match the OpenSeeFace wire format."""


@dataclass
class OsfFace:
    time: float
    id: int
    camera_resolution: tuple[float, float]
    right_eye_open: float
    left_eye_open: float
    success: bool
    pnp_error: float
    quaternion: tuple[float, float, float, float]
    euler: tuple[float, float, float]
    translation: tuple[float, float, float]
    confidences: list[float]
    points: list[tuple[float, float]]
    points_3d: list[tuple[float, float, float]]
    features: dict[str, float]


@dataclass
class ParsedOsfPacket:
    time: float
    faces: list[OsfFace]


def parse_osf_datagram(data: bytes) -> ParsedOsfPacket:
    """Parse one OpenSeeFace UDP datagram (one or more 1785-byte face blocks)."""
    if len(data) == 0 or len(data) % OSF_FACE_SIZE != 0:
        raise OsfPacketError(
            f"datagram size {len(data)} is not a multiple of {OSF_FACE_SIZE} bytes"
        )

    timestamp = struct.unpack_from("<d", data, 0)[0]
    faces: list[OsfFace] = []
    for offset in range(0, len(data), OSF_FACE_SIZE):
        faces.append(_parse_face(data, offset))
    return ParsedOsfPacket(time=timestamp, faces=faces)


def _parse_face(data: bytes, offset: int) -> OsfFace:
    o = offset
    end = offset + OSF_FACE_SIZE
    if end > len(data):
        raise OsfPacketError("truncated face block")

    (face_time,) = struct.unpack_from("<d", data, o)
    o += 8
    (face_id,) = struct.unpack_from("<i", data, o)
    o += 4
    width, height = struct.unpack_from("<ff", data, o)
    o += 8
    right_eye, left_eye = struct.unpack_from("<ff", data, o)
    o += 8
    (success_byte,) = struct.unpack_from("<B", data, o)
    o += 1
    (pnp_error,) = struct.unpack_from("<f", data, o)
    o += 4
    quaternion = struct.unpack_from("<ffff", data, o)
    o += 16
    euler = struct.unpack_from("<fff", data, o)
    o += 12
    translation = struct.unpack_from("<fff", data, o)
    o += 12

    confidences = list(struct.unpack_from(f"<{OSF_N_POINTS}f", data, o))
    o += OSF_N_POINTS * 4

    points = list(struct.unpack_from(f"<{OSF_N_POINTS * 2}f", data, o))
    o += OSF_N_POINTS * 8
    point_pairs = [(points[i + 1], points[i]) for i in range(0, len(points), 2)]  # wire order is (y, x)

    pts3d_flat = list(struct.unpack_from(f"<{OSF_N_POINTS_3D * 3}f", data, o))
    o += OSF_N_POINTS_3D * 12
    points_3d = [
        (pts3d_flat[i], pts3d_flat[i + 1], pts3d_flat[i + 2])
        for i in range(0, len(pts3d_flat), 3)
    ]

    feature_values = struct.unpack_from(f"<{OSF_N_FEATURES}f", data, o)
    o += OSF_N_FEATURES * 4

    assert o == end, "parser drift: consumed fewer bytes than the face block size"

    return OsfFace(
        time=face_time,
        id=face_id,
        camera_resolution=(width, height),
        right_eye_open=right_eye,
        left_eye_open=left_eye,
        success=bool(success_byte),
        pnp_error=pnp_error,
        quaternion=quaternion,
        euler=euler,
        translation=translation,
        confidences=confidences,
        points=point_pairs,
        points_3d=points_3d,
        features=dict(zip(OSF_FEATURE_NAMES, feature_values)),
    )

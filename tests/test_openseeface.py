"""Unit tests for the OpenSeeFace binary protocol parser and packet conversion."""

import struct

import pytest

from backend.backends.openseeface_backend import face_to_packet
from backend.backends.openseeface_protocol import (
    OSF_FACE_SIZE,
    OSF_FEATURE_NAMES,
    OsfPacketError,
    parse_osf_datagram,
)

VALID_POSE = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}


def build_face_block(
    *,
    time: float = 1234.5,
    face_id: int = 0,
    right_eye: float = 0.9,
    left_eye: float = 0.8,
    success: int = 1,
    pnp_error: float = 0.42,
    quaternion: tuple = (0.1, 0.2, 0.3, 0.9),
    euler: tuple = (10.0, -20.0, 30.0),
    translation: tuple = (1.0, 2.0, 3.0),
    features: tuple | None = None,
) -> bytes:
    if features is None:
        features = tuple(float(i) / 14.0 for i in range(len(OSF_FEATURE_NAMES)))
    block = struct.pack("<d", time)
    block += struct.pack("<i", face_id)
    block += struct.pack("<ff", 640.0, 360.0)
    block += struct.pack("<f", right_eye)
    block += struct.pack("<f", left_eye)
    block += struct.pack("<B", success)
    block += struct.pack("<f", pnp_error)
    block += struct.pack("<ffff", *quaternion)
    block += struct.pack("<fff", *euler)
    block += struct.pack("<fff", *translation)
    block += struct.pack(f"<{68}f", *([0.95] * 68))  # confidences
    block += struct.pack(f"<{68 * 2}f", *([1.5, 2.5] * 68))  # points (y, x) wire order
    block += struct.pack(f"<{70 * 3}f", *([0.0, 0.0, 0.0] * 70))  # 3D points
    block += struct.pack(f"<{len(OSF_FEATURE_NAMES)}f", *features)
    assert len(block) == OSF_FACE_SIZE
    return block


def test_parse_single_face():
    parsed = parse_osf_datagram(build_face_block())
    assert len(parsed.faces) == 1
    face = parsed.faces[0]
    assert face.time == pytest.approx(1234.5)
    assert face.id == 0
    assert face.camera_resolution == pytest.approx((640.0, 360.0))
    assert face.right_eye_open == pytest.approx(0.9)
    assert face.left_eye_open == pytest.approx(0.8)
    assert face.success is True
    assert face.pnp_error == pytest.approx(0.42)
    assert face.quaternion == pytest.approx((0.1, 0.2, 0.3, 0.9))
    assert face.euler == pytest.approx((10.0, -20.0, 30.0))
    assert face.translation == pytest.approx((1.0, 2.0, 3.0))


def test_parse_multi_face_datagram():
    data = build_face_block(face_id=0) + build_face_block(face_id=1, time=1234.6)
    parsed = parse_osf_datagram(data)
    assert len(parsed.faces) == 2
    assert [f.id for f in parsed.faces] == [0, 1]


def test_parse_rejects_bad_sizes():
    with pytest.raises(OsfPacketError):
        parse_osf_datagram(b"")
    with pytest.raises(OsfPacketError):
        parse_osf_datagram(b"x" * 100)
    with pytest.raises(OsfPacketError):
        parse_osf_datagram(build_face_block()[:-4])  # truncated


def test_features_names_and_order():
    face = parse_osf_datagram(build_face_block()).faces[0]
    assert list(face.features) == list(OSF_FEATURE_NAMES)
    assert face.features["mouth_open"] == pytest.approx(12.0 / 14.0)
    assert face.features["eye_l"] == pytest.approx(0.0)


def test_points_wire_order_is_y_x():
    face = parse_osf_datagram(build_face_block()).faces[0]
    # Wire packs (y=1.5, x=2.5); parser must expose (x, y).
    assert face.points[0] == pytest.approx((2.5, 1.5))


def test_face_to_packet_shape_and_timestamp():
    face = parse_osf_datagram(build_face_block(time=1.5)).faces[0]
    packet = face_to_packet(face)
    assert packet.t == 1500  # seconds -> epoch ms
    assert packet.engine == "openseeface"
    assert packet.conf == 1.0
    assert packet.shapes["eyeOpennessRight"] == pytest.approx(0.9)
    assert packet.shapes["eyeOpennessLeft"] == pytest.approx(0.8)
    assert packet.shapes["mouth_open"] == pytest.approx(12.0 / 14.0)
    assert packet.pose["rx"] == pytest.approx(10.0)
    assert packet.pose["tz"] == pytest.approx(3.0)
    assert packet.extra["osf"]["pnp_error"] == pytest.approx(0.42)
    assert packet.extra["osf"]["success"] is True


def test_face_to_packet_failure_maps_to_zero_confidence():
    face = parse_osf_datagram(build_face_block(success=0)).faces[0]
    packet = face_to_packet(face)
    assert packet.conf == 0.0
    assert packet.extra["osf"]["success"] is False

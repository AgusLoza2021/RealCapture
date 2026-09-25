"""Unit tests for the RealCapture packet schema (pure logic, no mediapipe)."""

import json

import pytest

from backend.common.packets import (
    PACKET_SCHEMA_VERSION,
    PacketValidationError,
    decode_packet,
    encode_packet,
    validate_packet_dict,
)

VALID_POSE = {
    "rx": 1.5,
    "ry": -12.0,
    "rz": 3.25,
    "tx": 0.1,
    "ty": -0.05,
    "tz": 0.6,
}
VALID_SHAPES = {"eyeBlinkLeft": 0.42, "jawOpen": 0.18, "mouthSmileLeft": 0.0}


def make_valid_dict() -> dict:
    return {
        "t": 1718345678901,
        "engine": "mediapipe",
        "conf": 0.97,
        "pose": dict(VALID_POSE),
        "shapes": dict(VALID_SHAPES),
    }


def test_schema_version_constant_exists():
    assert isinstance(PACKET_SCHEMA_VERSION, int)
    assert PACKET_SCHEMA_VERSION >= 1


def test_encode_decode_roundtrip():
    payload = encode_packet(
        t=1234, engine="mediapipe", conf=0.5, pose=VALID_POSE, shapes=VALID_SHAPES
    )
    assert isinstance(payload, bytes)
    packet = decode_packet(payload)
    assert packet.t == 1234
    assert packet.engine == "mediapipe"
    assert packet.conf == pytest.approx(0.5)
    assert packet.pose == VALID_POSE
    assert packet.shapes == VALID_SHAPES
    assert packet.extra == {}


def test_encoded_payload_is_compact_json():
    payload = encode_packet(t=1, engine="e", conf=0.0, pose=VALID_POSE, shapes={})
    parsed = json.loads(payload.decode("utf-8"))
    assert parsed["t"] == 1
    assert "extra" not in parsed  # empty extra omitted


def test_extra_field_roundtrip():
    payload = encode_packet(
        t=1,
        engine="openseeface",
        conf=1.0,
        pose=VALID_POSE,
        shapes={},
        extra={"raw_conf": 0.9},
    )
    packet = decode_packet(payload)
    assert packet.extra == {"raw_conf": 0.9}


def test_int_conf_accepted():
    raw = make_valid_dict()
    raw["conf"] = 1
    validate_packet_dict(raw)  # must not raise


def test_missing_required_field_rejected():
    raw = make_valid_dict()
    del raw["conf"]
    with pytest.raises(PacketValidationError, match="conf"):
        validate_packet_dict(raw)


def test_unknown_top_level_field_rejected():
    raw = make_valid_dict()
    raw["hacker"] = True
    with pytest.raises(PacketValidationError, match="unknown packet fields"):
        validate_packet_dict(raw)


def test_out_of_range_conf_rejected():
    raw = make_valid_dict()
    raw["conf"] = 1.5
    with pytest.raises(PacketValidationError, match="conf"):
        validate_packet_dict(raw)


def test_out_of_range_shape_rejected():
    raw = make_valid_dict()
    raw["shapes"]["jawOpen"] = -0.1
    with pytest.raises(PacketValidationError, match="jawOpen"):
        validate_packet_dict(raw)


def test_missing_pose_key_rejected():
    raw = make_valid_dict()
    del raw["pose"]["ry"]
    with pytest.raises(PacketValidationError, match="ry"):
        validate_packet_dict(raw)


def test_extra_pose_key_rejected():
    raw = make_valid_dict()
    raw["pose"]["w"] = 0.0
    with pytest.raises(PacketValidationError, match="pose has unknown keys"):
        validate_packet_dict(raw)


def test_non_finite_pose_rejected():
    raw = make_valid_dict()
    raw["pose"]["rx"] = float("nan")
    with pytest.raises(PacketValidationError, match="finite"):
        validate_packet_dict(raw)


def test_negative_timestamp_rejected():
    raw = make_valid_dict()
    raw["t"] = -5
    with pytest.raises(PacketValidationError, match="t"):
        validate_packet_dict(raw)


def test_empty_engine_rejected():
    raw = make_valid_dict()
    raw["engine"] = ""
    with pytest.raises(PacketValidationError, match="engine"):
        validate_packet_dict(raw)


def test_bool_conf_rejected():
    raw = make_valid_dict()
    raw["conf"] = True
    with pytest.raises(PacketValidationError, match="conf"):
        validate_packet_dict(raw)


def test_invalid_json_rejected():
    with pytest.raises(PacketValidationError, match="valid JSON"):
        decode_packet(b"{not json")


def test_invalid_utf8_rejected():
    with pytest.raises(PacketValidationError, match="UTF-8"):
        decode_packet(b"\xff\xfe\x00")


def test_non_object_payload_rejected():
    with pytest.raises(PacketValidationError, match="JSON object"):
        decode_packet(b"[1,2,3]")

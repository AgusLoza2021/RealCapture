"""Tests for RigProfile JSON schema: roundtrip, validation, file IO."""

import json

import pytest

from addon.rigprofile import BoneBinding, PointTransform, ProfileError, RigProfile, ShapeKeyBinding


def _sample_profile() -> RigProfile:
    return RigProfile(
        name="Test rig",
        head_bone="head",
        rig_kind="rigify",
        points=[PointTransform(role="jaw", channel="jawOpen", kind="location",
                               axis="Y", gain=0.06)],
        shapekey_bindings=[ShapeKeyBinding(channel="eyeBlinkLeft", target="Blink.L")],
        bone_bindings=[BoneBinding(point="jaw", target="jaw",
                                   constraint="copy_location")],
    )


class TestRoundtrip:
    def test_to_dict_from_dict(self):
        profile = _sample_profile()
        restored = RigProfile.from_dict(profile.to_dict())
        assert restored == profile

    def test_json_roundtrip(self):
        profile = _sample_profile()
        restored = RigProfile.from_json(profile.to_json())
        assert restored == profile

    def test_file_roundtrip(self, tmp_path):
        path = tmp_path / "rig.json"
        _sample_profile().save(str(path))
        restored = RigProfile.load(str(path))
        assert restored == _sample_profile()

    def test_document_shape(self):
        doc = _sample_profile().to_dict()
        assert doc["version"] == 1
        assert doc["kind"] == "realcapture-rig-profile"
        assert set(doc) == {"version", "kind", "name", "head_bone", "rig_kind",
                            "points", "shapekey_bindings", "bone_bindings"}


class TestValidation:
    def test_rejects_wrong_kind(self):
        with pytest.raises(ProfileError):
            RigProfile.from_dict({"kind": "other", "version": 1})

    def test_rejects_wrong_version(self):
        with pytest.raises(ProfileError):
            RigProfile.from_dict({"kind": "realcapture-rig-profile", "version": 99})

    def test_rejects_malformed_json(self):
        with pytest.raises(ProfileError):
            RigProfile.from_json("{not json")

    def test_rejects_missing_channel(self):
        with pytest.raises(ProfileError):
            ShapeKeyBinding.from_dict({"target": "Blink.L"})

    def test_rejects_unknown_constraint(self):
        with pytest.raises(ProfileError):
            BoneBinding.from_dict({"point": "jaw", "target": "jaw",
                                   "constraint": "black_magic"})

    def test_rejects_unknown_axis(self):
        with pytest.raises(ProfileError):
            PointTransform.from_dict({"role": "jaw", "channel": "jawOpen",
                                      "axis": "W"})

    def test_rejects_bad_axes_triple(self):
        with pytest.raises(ProfileError):
            BoneBinding.from_dict({"point": "jaw", "target": "jaw",
                                   "axes": [True, True]})


class TestDefaults:
    def test_minimal_document_loads(self):
        doc = {"version": 1, "kind": "realcapture-rig-profile", "name": "x"}
        profile = RigProfile.from_dict(doc)
        assert profile.points == []
        assert profile.shapekey_bindings == []
        assert profile.bone_bindings == []
        assert profile.rig_kind == "custom"

    def test_save_creates_valid_json_file(self, tmp_path):
        path = tmp_path / "rig.json"
        _sample_profile().save(str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["kind"] == "realcapture-rig-profile"

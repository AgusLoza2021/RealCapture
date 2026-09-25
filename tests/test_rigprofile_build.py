"""Tests for rigprofile.defaults and rigprofile.build."""

from addon.rigprofile import build, channels as ch, defaults
from addon.rigprofile.profile import RigProfile


class TestDefaultPointTransforms:
    def test_full_catalog_gives_all_roles(self):
        transforms = defaults.default_point_transforms(set(ch.ARKIT_CHANNELS))
        roles = {t.role for t in transforms}
        assert "jaw" in roles
        assert "eye_lid.L" in roles
        assert "eye_lid.R" in roles
        assert "mouth_corner.L" in roles

    def test_sided_roles_prefer_sided_channels(self):
        transforms = defaults.default_point_transforms(set(ch.ARKIT_CHANNELS))
        brow_l = [t for t in transforms if t.role == "brow.L"]
        channels = {t.channel for t in brow_l}
        assert "browOuterUpLeft" in channels
        assert "browInnerUp" in channels  # unsided fallback shared by both brows

    def test_missing_channels_are_skipped(self):
        catalog = {"jawOpen"}
        transforms = defaults.default_point_transforms(catalog)
        assert [t.role for t in transforms] == ["jaw"]
        assert transforms[0].channel == "jawOpen"

    def test_gaze_uses_two_channels_per_eye(self):
        transforms = defaults.default_point_transforms(set(ch.ARKIT_CHANNELS))
        eye_l = [t for t in transforms if t.role == "eye.L"]
        axes = {t.axis for t in eye_l}
        assert axes == {"X", "Z"}  # horizontal + vertical gaze components


class TestBuildProfile:
    def _proposals(self, kind, pairs):
        from addon.rigprofile.matcher import Proposal

        return [Proposal(key=key, kind=kind, target=target, confidence=0.9,
                         reason="alias") for key, target in pairs]

    def test_build_with_bones_includes_point_transforms(self):
        shape = self._proposals("shapekey", [("eyeBlinkLeft", "Blink.L")])
        bones = self._proposals("bone", [("jaw", "jaw"), ("eye_lid.L", "eyelid.T.L")])
        profile = build.build_profile(
            name="Test", shapekey_proposals=shape, bone_proposals=bones,
            channel_catalog=set(ch.ARKIT_CHANNELS), head_bone="head")
        assert isinstance(profile, RigProfile)
        assert profile.shapekey_bindings[0].target == "Blink.L"
        assert {b.point for b in profile.bone_bindings} == {"jaw", "eye_lid.L"}
        roles = {t.role for t in profile.points}
        assert roles == {"jaw", "eye_lid.L"}
        assert profile.head_bone == "head"

    def test_shapekey_only_profile_has_no_points(self):
        shape = self._proposals("shapekey", [("jawOpen", "Jaw_Open")])
        profile = build.build_profile("T", shape, [],
                                      channel_catalog=set(ch.ARKIT_CHANNELS))
        assert profile.points == []
        assert profile.bone_bindings == []

    def test_bone_without_driven_channels_is_dropped(self):
        # eye_lid role driven only by blink channels; exclude them all.
        catalog = {"jawOpen"}
        bones = self._proposals("bone", [("eye_lid.L", "eyelid.T.L")])
        profile = build.build_profile("T", [], bones, channel_catalog=catalog)
        assert profile.bone_bindings == []
        assert profile.points == []

    def test_unknown_shapekey_channel_ignored(self):
        shape = self._proposals("shapekey", [("notAChannel", "Whatever")])
        profile = build.build_profile("T", shape, [],
                                      channel_catalog=set(ch.ARKIT_CHANNELS))
        assert profile.shapekey_bindings == []

    def test_profile_roundtrips_after_build(self):
        shape = self._proposals("shapekey", [("eyeBlinkLeft", "Blink.L")])
        bones = self._proposals("bone", [("jaw", "jaw")])
        profile = build.build_profile("T", shape, bones,
                                      channel_catalog=set(ch.ARKIT_CHANNELS))
        restored = RigProfile.from_dict(profile.to_dict())
        assert restored == profile

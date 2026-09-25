"""Tests for rigprofile.channels: canonical vocabulary invariants."""

from addon.rigprofile import channels as ch


def test_arkit_has_52_channels():
    assert len(ch.ARKIT_CHANNELS) == 52
    assert len(set(ch.ARKIT_CHANNELS)) == 52


def test_sided_channels_are_consistent():
    for channel in ch.SIDED_CHANNELS:
        assert channel.endswith(("Left", "Right"))
        base = ch.channel_base(channel)
        assert not base.endswith(("left", "right"))


def test_channel_side():
    assert ch.channel_side("eyeBlinkLeft") == "L"
    assert ch.channel_side("eyeBlinkRight") == "R"
    assert ch.channel_side("jawOpen") is None


def test_channel_base_strips_side():
    assert ch.channel_base("eyeBlinkLeft") == "eyeblink"
    assert ch.channel_base("mouthSmileRight") == "mouthsmile"
    assert ch.channel_base("jawOpen") == "jawopen"


def test_point_roles_include_sides_and_singles():
    roles = ch.point_roles()
    assert "jaw" in roles
    assert "eye_lid.L" in roles
    assert "eye_lid.R" in roles
    assert "brow_inner" in roles
    assert len(roles) == 2 * 5 + 4  # 5 sided roles + 4 single roles

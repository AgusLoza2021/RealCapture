"""Tests for rigprofile.naming: standardization and side extraction."""

import pytest

from addon.rigprofile import naming


class TestStandardize:
    @pytest.mark.parametrize("raw,expected", [
        ("Jaw_Open", "jaw_open"),
        ("jawOpen", "jawopen"),
        ("jaw-open", "jaw_open"),
        ("jaw.open", "jaw_open"),
        ("Bip01_Head", "head"),
        ("mixamorig:Head", "head"),
        ("ValveBiped_Bip01_Head", "head"),
        ("DEF-jaw", "jaw"),
        ("jaw_Jnt", "jaw"),
        ("jaw_Bone", "jaw"),
        ("brow_ctrl", "brow"),
        ("  Jaw  ", "jaw"),
        ("jaw__open", "jaw_open"),
    ])
    def test_cases(self, raw, expected):
        assert naming.standardize(raw) == expected

    def test_does_not_eat_meaningful_text(self):
        # Prefix stripping must not consume the entire name.
        assert naming.standardize("def_") == "def"
        assert naming.standardize("bone") == "bone"


class TestSplitSide:
    @pytest.mark.parametrize("raw,expected_base,expected_side", [
        ("eye.L", "eye", "L"),
        ("eye.R", "eye", "R"),
        ("arm_r", "arm", "R"),
        ("arm-left", "arm", "L"),
        ("L_hand", "hand", "L"),
        ("R_shoulder", "shoulder", "R"),
        ("handLeft", "hand", "L"),
        ("EyeBlink_Left", "eyeblink", "L"),
        ("jaw", "jaw", None),
        ("lip_lower", "lip_lower", None),
        ("Jaw_Open", "jaw_open", None),
        ("head", "head", None),
    ])
    def test_cases(self, raw, expected_base, expected_side):
        base, side = naming.split_side(raw)
        assert (base, side) == (expected_base, expected_side)

    def test_side_and_prefixes_combine(self):
        # Rig-style prefixes are stripped BEFORE side detection.
        base, side = naming.split_side("Bip01_L_Hand")
        assert side == "L"
        assert "hand" in base

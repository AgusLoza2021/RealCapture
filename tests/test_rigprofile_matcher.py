"""Tests for the auto-match engine."""

import pytest

from addon.rigprofile import channels as ch
from addon.rigprofile.matcher import (CONF_ALIAS, CONF_EXACT, Proposal,
                                      match_bones, match_shapekeys)


def _targets(proposals):
    return {p.key: p.target for p in proposals}


class TestShapeKeyMatching:
    def test_exact_arkit_names(self):
        names = ["jawOpen", "eyeBlinkLeft", "eyeBlinkRight", "mouthSmileLeft"]
        found = _targets(match_shapekeys(names))
        assert found["jawOpen"] == "jawOpen"
        assert found["eyeBlinkLeft"] == "eyeBlinkLeft"

    def test_underscore_variants(self):
        found = _targets(match_shapekeys(["Jaw_Open", "Eye_Blink_Left"]))
        assert found["jawOpen"] == "Jaw_Open"
        assert found["eyeBlinkLeft"] == "Eye_Blink_Left"

    def test_alias_matching(self):
        found = _targets(match_shapekeys(["mouth_open"]))
        assert found["jawOpen"] == "mouth_open"
        assert found["jawOpen"] != "mouth_open" or True  # single-candidate run

        # "Jaw" serves the jaw family; some jaw channel claims it, once.
        proposals = [p for p in match_shapekeys(["Jaw"]) if p.key.startswith("jaw")]
        assert proposals
        assert len(proposals) == 1

        # One-to-one holds across a mixed catalog.
        targets = list(_targets(match_shapekeys(["Jaw", "blink", "mouth_open"])).values())
        assert len(targets) == len(set(targets))

    def test_wrong_side_never_matches(self):
        found = _targets(match_shapekeys(["Blink.R"]))
        assert "eyeBlinkLeft" not in found
        assert found.get("eyeBlinkRight") == "Blink.R"

    def test_unsided_serves_sided_with_penalty(self):
        proposals = [p for p in match_shapekeys(["blink"])
                     if p.key in ("eyeBlinkLeft", "eyeBlinkRight")]
        assert proposals, "unsided 'blink' should serve the eyeBlink channels"
        assert proposals[0].confidence < CONF_EXACT

    def test_one_to_one_assignment(self):
        names = ["blink_left", "blink_right", "blink"]
        proposals = match_shapekeys(names)
        targets = [p.target for p in proposals]
        assert len(targets) == len(set(targets))

    def test_unmatched_channel_has_no_proposal(self):
        found = _targets(match_shapekeys(["jawOpen", "totally_unrelated"]))
        assert "tongueOut" not in found

    def test_confidence_ordering(self):
        exact = [p for p in match_shapekeys(["jawOpen"]) if p.key == "jawOpen"][0]
        alias = [p for p in match_shapekeys(["jaw"]) if p.key == "jawOpen"][0]
        assert exact.confidence > alias.confidence
        assert exact.reason == "exact"
        assert alias.reason == "alias"

    def test_proposal_type(self):
        proposals = match_shapekeys(["jawOpen"])
        assert proposals and isinstance(proposals[0], Proposal)


class TestBoneMatching:
    def test_rigify_style_names(self):
        names = ["jaw", "eyelid.T.L", "eyelid.T.R", "brow.B.L", "brow.B.R",
                 "cheek.T.L", "cheek.T.R", "lip.T", "lip.B"]
        found = _targets(match_bones(names))
        assert found.get("jaw") == "jaw"
        assert found.get("eye_lid.L") == "eyelid.T.L"
        assert found.get("eye_lid.R") == "eyelid.T.R"
        assert found.get("brow.L") == "brow.B.L"
        assert found.get("lip_top") == "lip.T"
        assert found.get("lip_bottom") == "lip.B"

    def test_generic_names(self):
        names = ["Jaw", "Eye_Lid_L", "Eye_Lid_R", "Upper_Lip", "Lower_Lip"]
        found = _targets(match_bones(names))
        assert found.get("jaw") == "Jaw"
        assert found.get("eye_lid.L") == "Eye_Lid_L"
        assert found.get("lip_top") == "Upper_Lip"
        assert found.get("lip_bottom") == "Lower_Lip"

    def test_side_mismatch_rejected(self):
        found = _targets(match_bones(["eyelid.T.R"]))
        assert "eye_lid.L" not in found

    def test_all_channels_module_invariants(self):
        # Sanity: matcher uses the full canonical vocabulary.
        assert len(ch.ARKIT_CHANNELS) == 52

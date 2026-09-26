"""Pure tests for the head-bone selection and rest-deformation gate.

These must run with no Blender installed: everything tested lives in
addon/rigprofile/headbone.py, which never imports bpy.

The MPFB2 regression case encodes the measured defect (defect T9): a 1.667 m
MakeHuman character whose bone named 'head' sits at z = 0.697 m (chest height)
while the skull is held by FACS muscle bones at z = 1.56-1.65 m. Binding the
FPD empties to that bone displaced eye.L/eye.R by 0.908 m and the worst mesh
vertex by 0.8211 m with every shape key at 0.
"""

import math

import pytest

from addon.rigprofile.headbone import (
    HEAD_MIN_MARGIN_FRACTION,
    HEAD_NAME_PREFIX,
    REST_GATE_THRESHOLD,
    choose_head_bone,
    exceeds_rest_gate,
    highest_head_candidate,
    is_gate_measurable,
)

# Measured geometry of the MPFB2 regression character (metres).
MPFB_MESH_Z_MIN = 0.0
MPFB_MESH_Z_MAX = 1.667
MPFB_BAD_HEAD_Z = 0.697


def _mpfb_candidates() -> list[tuple[str, float]]:
    """The real character's relevant bones: the only 'head*' name is the
    chest-height stub; the skull joints are FACS muscles (never 'head*')."""
    return [
        ("head", MPFB_BAD_HEAD_Z),
        ("special05", 1.65),
        ("oculi01", 1.60),
        ("temporalis01", 1.56),
        ("neck", 0.60),
        ("spine01", 0.45),
    ]


class TestChooseHeadBone:
    def test_healthy_head_bone_near_top_is_chosen(self):
        # A normal rig: 'head' joint inside the skull, near the mesh top.
        candidates = [("neck", 1.30), ("head", 1.55), ("chin", 1.40)]
        assert choose_head_bone(candidates, 0.0, 1.667) == "head"

    def test_mpfb2_regression_chest_head_bone_returns_none(self):
        # The measured defect: 'head' at chest height must NOT be chosen,
        # even though it is the only bone whose name starts with 'head'.
        assert choose_head_bone(
            _mpfb_candidates(), MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) is None

    def test_bone_exactly_at_midpoint_is_rejected(self):
        midpoint = (MPFB_MESH_Z_MIN + MPFB_MESH_Z_MAX) / 2.0
        candidates = [("head", midpoint)]
        assert choose_head_bone(candidates, MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) is None

    def test_bone_below_midpoint_is_rejected(self):
        candidates = [("head", 0.4)]
        assert choose_head_bone(candidates, 0.0, 1.667) is None

    def test_bone_just_above_midpoint_without_margin_is_rejected(self):
        height = MPFB_MESH_Z_MAX - MPFB_MESH_Z_MIN
        midpoint = MPFB_MESH_Z_MIN + height / 2.0
        candidates = [("head", midpoint + HEAD_MIN_MARGIN_FRACTION * height * 0.5)]
        assert choose_head_bone(candidates, MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) is None

    def test_bone_above_midpoint_plus_margin_is_accepted(self):
        height = MPFB_MESH_Z_MAX - MPFB_MESH_Z_MIN
        midpoint = MPFB_MESH_Z_MIN + height / 2.0
        candidates = [("head", midpoint + HEAD_MIN_MARGIN_FRACTION * height)]
        assert choose_head_bone(candidates, MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) == "head"

    def test_highest_eligible_wins_when_several_qualify(self):
        candidates = [("head_01", 1.45), ("HEAD", 1.60), ("head", 1.30)]
        assert choose_head_bone(candidates, 0.0, 1.667) == "HEAD"

    def test_name_filtering_eligible_prefixes(self):
        # HEAD / head_01 are name-eligible (position decides). 'extra_head'
        # is NOT eligible: the rule is lower().startswith('head') and
        # 'extra_head' merely contains the prefix.
        height = MPFB_MESH_Z_MAX - MPFB_MESH_Z_MIN
        z = MPFB_MESH_Z_MIN + height * 0.9
        for name in ("HEAD", "head_01"):
            assert choose_head_bone([(name, z)], MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) == name
            assert choose_head_bone(
                [(name, MPFB_BAD_HEAD_Z)], MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) is None
        assert choose_head_bone(
            [("extra_head", z)], MPFB_MESH_Z_MIN, MPFB_MESH_Z_MAX) is None

    def test_non_head_names_never_eligible(self):
        candidates = [("neck", 1.60), ("spine01", 1.65)]
        assert choose_head_bone(candidates, 0.0, 1.667) is None
        assert highest_head_candidate(candidates) is None

    def test_headtop_nub_is_name_eligible(self):
        # 'headtop_nub'.lower() starts with 'head', so a nub joint inside
        # the skull is a legitimate anchor; a low one is still rejected.
        assert choose_head_bone([("HeadTop_Nub", 1.66)], 0.0, 1.667) == "HeadTop_Nub"
        assert choose_head_bone([("HeadTop_Nub", 0.7)], 0.0, 1.667) is None

    def test_no_candidates_returns_none(self):
        assert choose_head_bone([], 0.0, 1.667) is None

    def test_degenerate_mesh_height_returns_none(self):
        candidates = [("head", 1.0)]
        assert choose_head_bone(candidates, 1.0, 1.0) is None

    def test_default_prefix_constant_is_head(self):
        assert HEAD_NAME_PREFIX == "head"


class TestHighestHeadCandidate:
    def test_regression_reports_the_rejected_bone(self):
        # Even when nothing qualifies, the caller needs the best 'head*'
        # candidate for an actionable error message.
        name, z = highest_head_candidate(_mpfb_candidates())
        assert name == "head"
        assert math.isclose(z, MPFB_BAD_HEAD_Z)

    def test_none_when_no_head_named_bone(self):
        assert highest_head_candidate([("neck", 1.0), ("jaw", 1.1)]) is None

    def test_empty_candidates(self):
        assert highest_head_candidate([]) is None


class TestRestGate:
    def test_measured_mpfb2_damage_exceeds_gate(self):
        # The real measured displacement: 0.8211 m at rest with all shapes 0.
        assert exceeds_rest_gate(0.8211) is True

    def test_small_legitimate_displacement_passes(self):
        assert exceeds_rest_gate(0.0321) is False

    def test_exactly_at_threshold_is_not_exceeded(self):
        assert exceeds_rest_gate(REST_GATE_THRESHOLD) is False

    def test_just_above_threshold_is_exceeded(self):
        assert exceeds_rest_gate(REST_GATE_THRESHOLD + 1e-9) is True

    def test_zero_passes(self):
        assert exceeds_rest_gate(0.0) is False

    def test_default_threshold_is_quarter_metre(self):
        assert REST_GATE_THRESHOLD == pytest.approx(0.25)

    def test_custom_threshold(self):
        assert exceeds_rest_gate(0.05, threshold=0.04) is True
        assert exceeds_rest_gate(0.05, threshold=0.06) is False


class _StubKeyBlocks:
    """Minimal stand-in for Blender's key_blocks collection."""

    def __init__(self, names):
        self._names = list(names)

    def __contains__(self, name):
        return name in self._names


class _StubShapeKeys:
    def __init__(self, names):
        self.key_blocks = _StubKeyBlocks(names)


class _StubMeshData:
    def __init__(self, shape_keys):
        self.shape_keys = shape_keys


class _StubObject:
    def __init__(self, type_name="MESH", shape_keys=None):
        self.type = type_name
        self.data = _StubMeshData(shape_keys)


class TestGateSelectability:
    """The gate must be able to fail.

    The first version of the rest gate selected meshes by the marker
    property written by the shape-key bind, which happens AFTER the gate
    runs: the list was always empty, the measurement returned None,
    exceeds_rest_gate was never consulted, and the bind kept reporting 3
    bones and 11 point transforms over a mesh torn by 0.8211 m. These
    tests pin the rule that makes that impossible.
    """

    def test_shapekeyed_mesh_with_basis_is_measurable(self):
        assert is_gate_measurable(_StubObject(shape_keys=_StubShapeKeys(["Basis", "jawOpen"]))) is True

    def test_basis_only_is_still_measurable(self):
        assert is_gate_measurable(_StubObject(shape_keys=_StubShapeKeys(["Basis"]))) is True

    def test_mesh_without_shape_keys_is_not_measurable(self):
        assert is_gate_measurable(_StubObject(shape_keys=None)) is False

    def test_shape_keys_without_basis_are_not_measurable(self):
        assert is_gate_measurable(_StubObject(shape_keys=_StubShapeKeys(["jawOpen"]))) is False

    def test_non_mesh_object_is_not_measurable(self):
        # The armature the constraints live on is not the artifact that tears.
        assert is_gate_measurable(_StubObject(type_name="ARMATURE", shape_keys=_StubShapeKeys(["Basis"]))) is False

    def test_object_without_data_is_not_measurable(self):
        empty = _StubObject()
        empty.data = None
        assert is_gate_measurable(empty) is False

    def test_non_container_key_blocks_is_not_measurable(self):
        broken = _StubObject(shape_keys=_StubShapeKeys(["Basis"]))
        broken.data.shape_keys.key_blocks = 7
        assert is_gate_measurable(broken) is False

    def test_plain_object_is_not_measurable(self):
        assert is_gate_measurable(object()) is False

    def test_selection_does_not_depend_on_bind_order(self):
        # The property that broke the first gate: the marker is written by
        # the shape-key bind, so the selector must ignore it entirely.
        marked = _StubObject(shape_keys=_StubShapeKeys(["Basis"]))
        marked.get = lambda name: True  # the DRIVEN_PROP marker, set later
        assert is_gate_measurable(marked) is True

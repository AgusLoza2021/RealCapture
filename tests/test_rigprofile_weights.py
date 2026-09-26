"""Pure tests for the weight-zone operations.

These must run with no Blender installed: everything tested lives in
addon/rigprofile/weights.py, which never imports bpy. The refusal rules
are the point of the unit (this project already paid for a check that
reported success over nothing), so every refusal below is asserted to
raise WeightZoneError, never to return a quiet result.
"""

import dataclasses
import math

import pytest

from addon.rigprofile.weights import (
    WEIGHT_MAX,
    WEIGHT_MIN,
    ZONE_OPS,
    WeightZone,
    WeightZoneError,
    apply_zone_edit,
    changed_vertices,
    limit_influences,
    normalize_vertex,
)


def _zone(vertices, name="lid.L"):
    return WeightZone(name=name, vertices=tuple(vertices))


class TestModuleContract:
    def test_constants(self):
        assert WEIGHT_MIN == 0.0
        assert WEIGHT_MAX == 1.0
        assert ZONE_OPS == ("add", "subtract", "scale", "set")

    def test_error_is_a_value_error(self):
        # Same convention as ProfileError(ValueError).
        assert issubclass(WeightZoneError, ValueError)


class TestWeightZoneConstruction:
    def test_stores_name_and_sorted_vertices(self):
        zone = _zone((5, 1, 3))
        assert zone.name == "lid.L"
        assert zone.vertices == (1, 3, 5)

    def test_deterministic_ordering_regardless_of_input(self):
        assert _zone((9, 0, 4)) == _zone((0, 4, 9)) == _zone((4, 9, 0))

    def test_is_frozen(self):
        zone = _zone((1,))
        with pytest.raises(dataclasses.FrozenInstanceError):
            zone.name = "other"

    def test_rejects_empty_name(self):
        with pytest.raises(WeightZoneError, match="''"):
            WeightZone(name="", vertices=(1,))

    def test_rejects_whitespace_only_name(self):
        with pytest.raises(WeightZoneError, match="'   '"):
            WeightZone(name="   ", vertices=(1,))

    def test_rejects_empty_selection(self):
        # Operating on nothing is a refusal, never a silent no-op.
        with pytest.raises(WeightZoneError, match="empty selection"):
            WeightZone(name="lid.L", vertices=())

    def test_rejects_negative_index_naming_it(self):
        with pytest.raises(WeightZoneError, match="-2"):
            WeightZone(name="lid.L", vertices=(1, -2))

    def test_rejects_duplicate_index_naming_it(self):
        with pytest.raises(WeightZoneError, match="duplicate"):
            WeightZone(name="lid.L", vertices=(3, 7, 3))

    def test_rejects_non_int_index(self):
        with pytest.raises(WeightZoneError, match="must be an int"):
            WeightZone(name="lid.L", vertices=(1, "2"))

    def test_rejects_non_tuple_vertices(self):
        with pytest.raises(WeightZoneError, match="tuple"):
            WeightZone(name="lid.L", vertices=[1, 2])


class TestWeightZoneSerialisation:
    def test_roundtrip(self):
        zone = _zone((5, 1, 3), name="brow.R")
        assert WeightZone.from_dict(zone.to_dict()) == zone

    def test_from_dict_sorts_and_revalidates_through_constructor(self):
        zone = WeightZone.from_dict({"name": "z", "vertices": [5, 1, 3]})
        assert zone.vertices == (1, 3, 5)

    def test_from_dict_bypasses_no_rule(self):
        with pytest.raises(WeightZoneError):
            WeightZone.from_dict({"name": "", "vertices": [1]})
        with pytest.raises(WeightZoneError):
            WeightZone.from_dict({"name": "z", "vertices": []})
        with pytest.raises(WeightZoneError):
            WeightZone.from_dict({"name": "z", "vertices": [2, 2]})
        with pytest.raises(WeightZoneError):
            WeightZone.from_dict({"name": "z", "vertices": [-1]})
        with pytest.raises(WeightZoneError):
            WeightZone.from_dict({"name": "z"})

    def test_from_dict_rejects_non_document(self):
        with pytest.raises(WeightZoneError):
            WeightZone.from_dict(["z", [1]])


class TestApplyZoneEditOps:
    def test_add(self):
        result = apply_zone_edit({1: 0.2}, _zone((1,)), "add", 0.3)
        assert result == {1: pytest.approx(0.5)}

    def test_subtract(self):
        result = apply_zone_edit({1: 0.8}, _zone((1,)), "subtract", 0.3)
        assert result == {1: pytest.approx(0.5)}

    def test_scale(self):
        result = apply_zone_edit({1: 0.4}, _zone((1,)), "scale", 0.5)
        assert result == {1: pytest.approx(0.2)}

    def test_set(self):
        result = apply_zone_edit({1: 0.4}, _zone((1,)), "set", 0.9)
        assert result == {1: pytest.approx(0.9)}

    def test_clamped_at_the_top(self):
        assert apply_zone_edit({1: 0.9}, _zone((1,)), "add", 0.5) == {1: 1.0}
        assert apply_zone_edit({1: 0.8}, _zone((1,)), "scale", 2.0) == {1: 1.0}
        assert apply_zone_edit({1: 0.2}, _zone((1,)), "set", 5.0) == {1: 1.0}

    def test_clamped_at_the_bottom(self):
        assert apply_zone_edit({1: 0.1}, _zone((1,)), "subtract", 0.5) == {1: 0.0}
        assert apply_zone_edit({1: 0.4}, _zone((1,)), "scale", 0.0) == {1: 0.0}
        assert apply_zone_edit({1: 0.2}, _zone((1,)), "set", -3.0) == {1: 0.0}

    def test_zone_vertex_absent_enters_at_zero(self):
        # Vertex 5 is in the zone but absent from the input; vertex 1 is
        # outside the zone and passes through untouched.
        result = apply_zone_edit({1: 0.5}, _zone((5,)), "add", 0.3)
        assert result == {1: 0.5, 5: pytest.approx(0.3)}

    def test_outside_vertex_passes_through_clamped(self):
        result = apply_zone_edit({1: 1.7, 2: -0.4}, _zone((3,)), "set", 0.5)
        assert result == {3: 0.5, 1: 1.0, 2: 0.0}

    def test_input_mapping_is_never_mutated(self):
        weights = {1: 0.5, 2: 1.7}
        snapshot = dict(weights)
        result = apply_zone_edit(weights, _zone((1,)), "add", 0.5)
        assert weights == snapshot
        assert result is not weights

    def test_unknown_op_raises_naming_it(self):
        with pytest.raises(WeightZoneError, match="multiply"):
            apply_zone_edit({1: 0.5}, _zone((1,)), "multiply", 2.0)

    def test_non_finite_value_raises(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(WeightZoneError, match="non-finite"):
                apply_zone_edit({1: 0.5}, _zone((1,)), "add", bad)

    def test_non_finite_weight_in_input_raises(self):
        # Even outside the zone: a non-finite weight poisons the mapping.
        with pytest.raises(WeightZoneError, match="non-finite"):
            apply_zone_edit({1: 0.5, 7: float("nan")}, _zone((1,)), "add", 0.1)
        with pytest.raises(WeightZoneError, match="non-finite"):
            apply_zone_edit({1: float("inf")}, _zone((1,)), "add", 0.1)

    def test_non_numeric_value_raises(self):
        with pytest.raises(WeightZoneError):
            apply_zone_edit({1: 0.5}, _zone((1,)), "add", "0.5")


class TestNormalizeVertex:
    def test_sums_to_one(self):
        result = normalize_vertex({"a": 0.3, "b": 0.1})
        assert result == {"a": pytest.approx(0.75), "b": pytest.approx(0.25)}
        assert math.isclose(sum(result.values()), 1.0)

    def test_all_zero_stays_all_zero(self):
        # Dividing by zero would produce NaN and destroy every group.
        weights = {"a": 0.0, "b": 0.0}
        result = normalize_vertex(weights)
        assert result == {"a": 0.0, "b": 0.0}
        assert result is not weights

    def test_empty_mapping_returns_empty_mapping(self):
        assert normalize_vertex({}) == {}

    def test_negative_raises(self):
        with pytest.raises(WeightZoneError, match="negative"):
            normalize_vertex({"a": 0.5, "b": -0.1})

    def test_non_finite_raises(self):
        with pytest.raises(WeightZoneError, match="non-finite"):
            normalize_vertex({"a": float("nan")})
        with pytest.raises(WeightZoneError, match="non-finite"):
            normalize_vertex({"a": float("inf")})

    def test_input_unchanged_and_new_dict_returned(self):
        weights = {"a": 1.0, "b": 3.0}
        result = normalize_vertex(weights)
        assert weights == {"a": 1.0, "b": 3.0}
        assert result is not weights


class TestLimitInfluences:
    def _vertex(self):
        return {"a": 0.5, "b": 0.1, "c": 0.9, "d": 0.3, "e": 0.7, "f": 0.05}

    def test_keeps_largest_four_by_default(self):
        # Default 4: VRM and glTF cap skin influences at four.
        assert set(limit_influences(self._vertex())) == {"c", "e", "a", "d"}

    def test_explicit_limit(self):
        assert set(limit_influences(self._vertex(), 2)) == {"c", "e"}

    def test_deterministic_tie_break_descending_weight_then_name(self):
        weights = {"b": 0.5, "a": 0.5, "d": 0.9, "c": 0.5, "e": 0.1}
        result = limit_influences(weights, 3)
        assert list(result) == ["d", "a", "b"]

    def test_fewer_than_limit_returns_equal_copy(self):
        weights = {"a": 0.5}
        result = limit_influences(weights, 4)
        assert result == weights
        assert result is not weights

    def test_normalize_false_keeps_raw_values(self):
        # Blender's "Limit Total" does not renormalize either: the kept
        # subset may sum to less than 1.0, and that must stay visible.
        result = limit_influences({"a": 0.6, "b": 0.2, "c": 0.1}, 2)
        assert result == {"a": 0.6, "b": 0.2}

    def test_normalize_true_renormalizes_kept_subset(self):
        result = limit_influences({"a": 0.6, "b": 0.2, "c": 0.1}, 2,
                                  normalize=True)
        assert result == {"a": pytest.approx(0.75), "b": pytest.approx(0.25)}

    def test_rejects_max_influences_below_one(self):
        with pytest.raises(WeightZoneError):
            limit_influences({"a": 0.5}, 0)
        with pytest.raises(WeightZoneError):
            limit_influences({"a": 0.5}, -1)

    def test_rejects_non_integer_max_influences(self):
        for bad in ("4", 4.5, 4.0, None):
            with pytest.raises(WeightZoneError, match="max_influences"):
                limit_influences({"a": 0.5}, bad)

    def test_rejects_bool_max_influences(self):
        # bool is an int subclass but is not a valid influence count.
        with pytest.raises(WeightZoneError, match="max_influences"):
            limit_influences({"a": 0.5}, True)
        with pytest.raises(WeightZoneError, match="max_influences"):
            limit_influences({"a": 0.5}, False)

    def test_rejects_non_finite_weights(self):
        with pytest.raises(WeightZoneError, match="non-finite"):
            limit_influences({"a": float("nan")})
        with pytest.raises(WeightZoneError, match="non-finite"):
            limit_influences({"a": 0.5, "b": float("-inf")})

    def test_input_unchanged(self):
        weights = {"a": 0.6, "b": 0.2, "c": 0.1}
        snapshot = dict(weights)
        limit_influences(weights, 2, normalize=True)
        assert weights == snapshot


class TestChangedVertices:
    def test_reports_only_differing_vertices_sorted(self):
        before = {1: 0.5, 2: 0.2, 4: 0.9}
        after = {1: 0.5, 2: 0.8, 4: 0.1}
        assert changed_vertices(before, after) == (2, 4)

    def test_key_present_on_only_one_side(self):
        # A key removed on one side is compared against the 0.0 default.
        assert changed_vertices({1: 0.5}, {}) == (1,)
        assert changed_vertices({}, {1: 0.5}) == (1,)

    def test_missing_key_read_as_zero_is_not_a_change(self):
        assert changed_vertices({1: 0.0}, {}) == ()
        assert changed_vertices({}, {1: 0.0}) == ()

    def test_exact_float_comparison(self):
        # 0.1 + 0.2 != 0.3 in float: the difference must be reported.
        assert changed_vertices({1: 0.1 + 0.2}, {1: 0.3}) == (1,)

    def test_identical_mappings_report_nothing(self):
        assert changed_vertices({1: 0.5}, {1: 0.5}) == ()
        assert changed_vertices({}, {}) == ()

    def test_result_is_sorted(self):
        result = changed_vertices({9: 0.1, 2: 0.1}, {9: 0.2, 2: 0.2})
        assert result == (2, 9)

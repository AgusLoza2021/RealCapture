"""Tests for the connection-status truth table (pure model, no I/O).

Pins the frozen contract: two thresholds per signal, absent/unknown is red
with a reason, the bind-in-effect semantics for the Blender light, and the
single-constructor honesty invariant (proven by mutation).
"""

from __future__ import annotations

import pytest

from backend.dashboard.status_model import (
    BLENDER_FRESH_S,
    BLENDER_STALE_S,
    CAMERA_FRESH_S,
    CAMERA_STALE_S,
    GREEN,
    PACKETS_FRESH_S,
    PACKETS_STALE_S,
    RED,
    REST_GATE_THRESHOLD_M,
    YELLOW,
    build_connections,
    make_light,
)


def _light(connections: list, connection_id: str) -> dict:
    return next(entry for entry in connections if entry["id"] == connection_id)


class TestThresholdConstants:
    def test_fresh_is_strictly_below_stale_for_every_signal(self) -> None:
        assert CAMERA_FRESH_S < CAMERA_STALE_S
        assert PACKETS_FRESH_S < PACKETS_STALE_S
        assert BLENDER_FRESH_S < BLENDER_STALE_S

    def test_rest_gate_threshold_matches_the_addon_source_of_truth(self) -> None:
        assert REST_GATE_THRESHOLD_M == 0.25


class TestTwoThresholdRule:
    """Camera and packets share the same rule; both are pinned at boundaries."""

    @pytest.mark.parametrize("connection_id", ["camera", "packets"])
    @pytest.mark.parametrize(
        "fresh_s, stale_s",
        [(CAMERA_FRESH_S, CAMERA_STALE_S), (PACKETS_FRESH_S, PACKETS_STALE_S)],
    )
    def test_age_exactly_at_fresh_is_green(self, connection_id: str, fresh_s: float, stale_s: float) -> None:
        camera_age = fresh_s if connection_id == "camera" else None
        packets_age = fresh_s if connection_id == "packets" else None
        blender_age = 0.1  # healthy, so it cannot interfere
        connections = build_connections(camera_age, packets_age, blender_age, {"mode": "shape_keys", "channels": 5})
        assert _light(connections, connection_id)["state"] == GREEN

    @pytest.mark.parametrize("connection_id", ["camera", "packets"])
    def test_age_exactly_at_stale_is_yellow(self, connection_id: str) -> None:
        age = CAMERA_STALE_S if connection_id == "camera" else PACKETS_STALE_S
        connections = build_connections(
            age if connection_id == "camera" else 0.1,
            age if connection_id == "packets" else 0.1,
            0.1,
            {"mode": "shape_keys", "channels": 5},
        )
        light = _light(connections, connection_id)
        assert light["state"] == YELLOW
        assert light["reason"]

    @pytest.mark.parametrize("connection_id", ["camera", "packets"])
    def test_age_just_above_stale_is_red(self, connection_id: str) -> None:
        age = (CAMERA_STALE_S if connection_id == "camera" else PACKETS_STALE_S) + 0.01
        connections = build_connections(
            age if connection_id == "camera" else 0.1,
            age if connection_id == "packets" else 0.1,
            0.1,
            {"mode": "shape_keys", "channels": 5},
        )
        light = _light(connections, connection_id)
        assert light["state"] == RED
        assert light["reason"]

    @pytest.mark.parametrize("connection_id", ["camera", "packets"])
    def test_unknown_age_is_red_with_a_reason(self, connection_id: str) -> None:
        connections = build_connections(
            None if connection_id == "camera" else 0.1,
            None if connection_id == "packets" else 0.1,
            0.1,
            {"mode": "shape_keys", "channels": 5},
        )
        light = _light(connections, connection_id)
        assert light["state"] == RED
        assert light["reason"].strip()


class TestBlenderLight:
    def _build(self, age_s: float | None, bind: dict | None) -> dict:
        return _light(build_connections(0.1, 0.1, age_s, bind), "blender")

    def test_healthy_heartbeat_with_bind_in_effect_within_gate_is_green(self) -> None:
        light = self._build(0.5, {"mode": "point_bones", "channels": 6, "rest_displacement_m": 0.01})
        assert light["state"] == GREEN

    def test_refused_bone_path_with_working_shape_keys_fallback_is_green(self) -> None:
        bind = {
            "mode": "shape_keys",
            "channels": 52,
            "rest_displacement_m": 0.0,
            "refused_rest_displacement_m": 0.83,
        }
        light = self._build(0.5, bind)
        assert light["state"] == GREEN
        # Informational reason IS wanted on green, and must carry the refusal.
        assert light["reason"].strip()
        assert "0.83" in light["reason"]
        assert "refused_rest_displacement_m" in light["reason"]

    def test_age_exactly_at_fresh_is_green(self) -> None:
        light = self._build(BLENDER_FRESH_S, {"mode": "shape_keys", "channels": 52})
        assert light["state"] == GREEN

    def test_age_exactly_at_stale_is_yellow(self) -> None:
        light = self._build(BLENDER_STALE_S, {"mode": "shape_keys", "channels": 52})
        assert light["state"] == YELLOW
        assert light["reason"].strip()

    def test_age_just_above_stale_is_red(self) -> None:
        light = self._build(BLENDER_STALE_S + 0.01, {"mode": "shape_keys", "channels": 52})
        assert light["state"] == RED
        assert light["reason"].strip()

    def test_missing_heartbeat_is_red_with_a_reason(self) -> None:
        light = self._build(None, {"mode": "shape_keys", "channels": 52})
        assert light["state"] == RED
        assert light["reason"].strip()

    def test_stale_heartbeat_with_a_torn_active_bind_is_red_not_yellow(self) -> None:
        bind = {"mode": "point_bones", "channels": 6, "rest_displacement_m": 0.4}
        light = self._build((BLENDER_FRESH_S + BLENDER_STALE_S) / 2.0, bind)
        assert light["state"] == RED

    def test_mode_none_is_yellow(self) -> None:
        light = self._build(0.5, {"mode": "none", "channels": 0})
        assert light["state"] == YELLOW
        assert "none" in light["reason"]

    def test_active_point_bones_bind_above_the_gate_is_red(self) -> None:
        bind = {"mode": "point_bones", "channels": 6, "rest_displacement_m": 0.4}
        light = self._build(0.5, bind)
        assert light["state"] == RED
        assert light["reason"].strip()

    def test_residual_above_the_gate_on_shape_keys_is_yellow(self) -> None:
        bind = {"mode": "shape_keys", "channels": 52, "rest_displacement_m": 0.3}
        light = self._build(0.5, bind)
        assert light["state"] == YELLOW
        assert light["reason"].strip()

    def test_absent_bind_report_with_fresh_heartbeat_is_red(self) -> None:
        light = self._build(0.5, None)
        assert light["state"] == RED
        assert light["reason"].strip()


class TestHonestyInvariant:
    def test_non_green_light_with_empty_reason_raises(self) -> None:
        with pytest.raises(ValueError):
            make_light(RED)
        with pytest.raises(ValueError):
            make_light(YELLOW, "")

    def test_non_green_light_with_whitespace_reason_raises(self) -> None:
        with pytest.raises(ValueError):
            make_light(RED, "   ")

    def test_green_light_with_empty_reason_is_allowed(self) -> None:
        light = make_light(GREEN)
        assert light == {"state": GREEN, "reason": "", "detail": {}}

    def test_unknown_state_raises(self) -> None:
        with pytest.raises(ValueError):
            make_light("blue", "not a real state")

    @pytest.mark.parametrize(
        "camera_age, packets_age, blender_age, bind",
        [
            (None, None, None, None),
            (0.1, None, 0.1, {"mode": "shape_keys", "channels": 52}),
            (1.5, 0.1, 0.1, {"mode": "none", "channels": 0}),
            (3.0, 0.1, 6.0, {"mode": "shape_keys", "channels": 52}),
            (0.1, 0.1, 0.1, {"mode": "point_bones", "channels": 6, "rest_displacement_m": 0.9}),
            (0.1, 0.1, 0.1, {"mode": "shape_keys", "channels": 52, "rest_displacement_m": 0.3}),
            (0.1, 0.1, 0.1, {"weird": True}),
        ],
    )
    def test_build_connections_never_returns_non_green_with_empty_reason(
        self,
        camera_age: float | None,
        packets_age: float | None,
        blender_age: float | None,
        bind: dict | None,
    ) -> None:
        for light in build_connections(camera_age, packets_age, blender_age, bind):
            if light["state"] != GREEN:
                assert light["reason"].strip(), f"{light['id']} lied with an empty reason"


class TestContractShape:
    def test_lights_come_in_contract_order_with_contract_ids_and_labels(self) -> None:
        connections = build_connections(0.1, 0.1, 0.1, {"mode": "shape_keys", "channels": 52})
        assert [(entry["id"], entry["label"]) for entry in connections] == [
            ("camera", "Camera"),
            ("packets", "Packets to Blender"),
            ("blender", "Blender rig"),
        ]

    def test_every_light_carries_state_reason_and_detail_keys(self) -> None:
        for light in build_connections(None, None, None, None):
            assert set(light) == {"id", "label", "state", "reason", "detail"}

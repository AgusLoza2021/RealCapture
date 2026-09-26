"""Connection lights through the real ASGI app: /api/status carries them.

Uses ``fastapi.testclient.TestClient`` (httpx) against ``create_app``, with
a fake camera-age callable and a duck-typed fake Blender source — no real
camera, no Blender, no sockets.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from backend.dashboard.hub import BroadcastHub, DashboardHub  # noqa: E402
from backend.dashboard.server import create_app  # noqa: E402

HEALTHY_BIND = {
    "mode": "shape_keys",
    "channels": 52,
    "head_bone": None,
    "rest_displacement_m": 0.0,
    "refused_rest_displacement_m": None,
}

REFUSED_BIND = {
    "mode": "shape_keys",
    "channels": 52,
    "head_bone": None,
    "rest_displacement_m": 0.01,
    "refused_rest_displacement_m": 0.83,
}


class FakeBlenderSource:
    """Duck-typed stand-in for the W3 HeartbeatTracker."""

    def __init__(self, age_s: float | None = 0.5, bind: dict | None = None) -> None:
        self._age_s = age_s
        self._bind = bind

    def age_s(self, now: float | None = None) -> float | None:
        return self._age_s

    def bind_report(self) -> dict | None:
        return dict(self._bind) if self._bind is not None else None


def _status(hub: DashboardHub) -> dict:
    client = TestClient(create_app(hub, BroadcastHub()))
    response = client.get("/api/status")
    assert response.status_code == 200
    client.close()
    return response.json()


def _by_id(connections: list, connection_id: str) -> dict:
    return next(entry for entry in connections if entry["id"] == connection_id)


class TestConnectionsWithNoSources:
    def test_status_carries_connections_in_contract_order(self) -> None:
        body = _status(DashboardHub())
        connections = body["connections"]
        assert [entry["id"] for entry in connections] == ["camera", "packets", "blender"]
        assert [entry["label"] for entry in connections] == [
            "Camera",
            "Packets to Blender",
            "Blender rig",
        ]

    def test_with_no_sources_every_light_is_non_green_with_a_reason(self) -> None:
        body = _status(DashboardHub())
        for light in body["connections"]:
            assert light["state"] != "green", f"{light['id']} went green on silence"
            assert light["reason"].strip(), f"{light['id']} has no reason"

    def test_existing_snapshot_keys_survive_next_to_connections(self) -> None:
        body = _status(DashboardHub())
        for key in ("status", "packets_sent", "fps", "record", "channels"):
            assert key in body


class TestConnectionsWithSources:
    def test_fake_camera_age_and_fake_blender_source_light_up(self) -> None:
        hub = DashboardHub(camera_age_s=lambda: 0.2, blender_source=FakeBlenderSource(0.5, HEALTHY_BIND))
        connections = _status(hub)["connections"]
        assert _by_id(connections, "camera")["state"] == "green"
        assert _by_id(connections, "blender")["state"] == "green"
        # No packet was ever recorded: the packets light stays honest.
        assert _by_id(connections, "packets")["state"] == "red"

    def test_refused_bone_path_is_green_with_informational_reason(self) -> None:
        hub = DashboardHub(camera_age_s=lambda: 0.2, blender_source=FakeBlenderSource(0.5, REFUSED_BIND))
        light = _by_id(_status(hub)["connections"], "blender")
        assert light["state"] == "green"
        assert "refused_rest_displacement_m" in light["reason"]

    def test_degraded_blender_bind_is_yellow_through_the_app(self) -> None:
        bind = dict(HEALTHY_BIND, mode="none", channels=0)
        hub = DashboardHub(camera_age_s=lambda: 0.2, blender_source=FakeBlenderSource(0.5, bind))
        light = _by_id(_status(hub)["connections"], "blender")
        assert light["state"] == "yellow"
        assert light["reason"].strip()

    def test_absent_blender_source_is_red_through_the_app(self) -> None:
        hub = DashboardHub(camera_age_s=lambda: 0.2)
        light = _by_id(_status(hub)["connections"], "blender")
        assert light["state"] == "red"
        assert light["reason"].strip()

    def test_camera_source_returning_none_is_red_through_the_app(self) -> None:
        hub = DashboardHub(camera_age_s=lambda: None, blender_source=FakeBlenderSource(0.5, HEALTHY_BIND))
        light = _by_id(_status(hub)["connections"], "camera")
        assert light["state"] == "red"
        assert light["reason"].strip()

    def test_recorded_packets_turn_the_packets_light_green(self) -> None:
        hub = DashboardHub(camera_age_s=lambda: 0.2, blender_source=FakeBlenderSource(0.5, HEALTHY_BIND))
        hub.record_sent(shapes={"jawOpen": 0.5}, conf=0.9, packet_t=1, proc_ms=1.0, now=hub._clock())
        light = _by_id(_status(hub)["connections"], "packets")
        assert light["state"] == "green"

"""Tests for the companion dashboard HTTP/WS server (fastapi required)."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from backend.dashboard.hub import BroadcastHub, DashboardHub, STATUS_RUNNING  # noqa: E402
from backend.dashboard.server import DashboardControls, SnapshotBridge, create_app  # noqa: E402


class StubControls(DashboardControls):
    """Controls that record calls instead of touching a real capture process."""

    def __init__(self) -> None:
        super().__init__(stop_capture=self._stop, set_record=self._record)
        self.stopped = False
        self.record_calls: list = []

    def _stop(self) -> None:
        self.stopped = True

    def _record(self, active: bool, path: str | None) -> None:
        self.record_calls.append((active, path))


@pytest.fixture()
def env():
    hub = DashboardHub()
    broadcast = BroadcastHub()
    controls = StubControls()
    app = create_app(hub, broadcast, controls)
    client = TestClient(app)
    yield client, hub, controls
    client.close()


def _running_hub(hub: DashboardHub) -> None:
    hub.begin_capture("mediapipe", "127.0.0.1", 11111)
    hub.record_sent(shapes={"jawOpen": 0.7}, conf=0.9, packet_t=1, proc_ms=1.5)


class TestRest:
    def test_status_reflects_hub(self, env) -> None:
        client, hub, _ = env
        assert client.get("/api/status").json()["status"] == "idle"
        _running_hub(hub)
        body = client.get("/api/status").json()
        assert body["status"] == STATUS_RUNNING
        assert body["packets_sent"] == 1

    def test_record_toggle(self, env) -> None:
        client, hub, controls = env
        response = client.post("/api/record", json={"active": True, "path": "s.jsonl"})
        assert response.json() == {"ok": True, "record": {"active": True, "path": "s.jsonl"}}
        assert controls.record_calls == [(True, "s.jsonl")]
        client.post("/api/record", json={"active": False})
        assert controls.record_calls[-1] == (False, None)

    def test_stop_capture(self, env) -> None:
        client, _, controls = env
        assert client.post("/api/capture/stop").json() == {"ok": True, "status": "stopping"}
        assert controls.stopped is True

    def test_controls_without_wiring_return_409(self) -> None:
        app = create_app(DashboardHub())
        client = TestClient(app)
        assert client.post("/api/capture/stop").status_code == 409
        assert client.post("/api/record", json={"active": True}).status_code == 409
        client.close()

    def test_index_served(self, env) -> None:
        client, _, _ = env
        response = client.get("/")
        assert response.status_code == 200
        assert "RealCapture" in response.text


class TestWebSocket:
    def test_ws_pushes_initial_and_published_snapshots(self, env) -> None:
        client, hub, _ = env
        broadcast = BroadcastHub()  # not wired to hub here; publish manually
        # Rebuild a client whose broadcast we control:
        hub2 = DashboardHub()
        app = create_app(hub2, broadcast, StubControls())
        with TestClient(app) as ws_client:
            with ws_client.websocket_connect("/ws") as ws:
                first = ws.receive_json()
                assert first["status"] == "idle"
                hub2.begin_capture("openseeface", "127.0.0.1", 11111)
                broadcast.publish(hub2.snapshot())
                pushed = ws.receive_json()
                assert pushed["status"] == STATUS_RUNNING
                assert pushed["engine"] == "openseeface"

    def test_ws_idle_ping_keeps_connection_alive(self, env) -> None:
        client, _, _ = env
        hub = DashboardHub()
        app = create_app(hub, BroadcastHub(), StubControls())
        with TestClient(app) as ws_client:
            with ws_client.websocket_connect("/ws") as ws:
                ws.receive_json()  # initial snapshot
                ping = ws.receive_json()  # idle timeout -> ping
                assert ping == {"kind": "ping"}


class TestSnapshotBridge:
    def test_next_snapshot_returns_published_value(self) -> None:
        import asyncio

        broadcast = BroadcastHub()
        bridge = SnapshotBridge(broadcast)

        async def scenario() -> dict | None:
            loop = asyncio.get_running_loop()
            event = asyncio.Event()
            bridge.bind(loop, event)
            task = asyncio.create_task(bridge.next_snapshot(timeout=5.0))
            await asyncio.sleep(0.05)
            broadcast.publish({"hello": 1})
            return await task

        snapshot = asyncio.run(scenario())
        assert snapshot == {"hello": 1}
        bridge.close()

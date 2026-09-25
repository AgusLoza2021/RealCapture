"""Tests for the companion dashboard hub (pure logic, no web framework)."""

from __future__ import annotations

import json
import threading

import pytest

from backend.dashboard.hub import (
    ACTIVITY_HALF_LIFE_S,
    BroadcastHub,
    DashboardHub,
    RATE_WINDOW_S,
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_STOPPED,
)

SHAPES = {"jawOpen": 0.8, "eyeBlink_L": 0.1, "browUp_R": 0.5}


class FakeClock:
    """Deterministic monotonic clock driven by the test."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


def _packet(hub: DashboardHub, clock: FakeClock, shapes: dict = SHAPES, proc_ms: float = 2.0) -> None:
    clock.advance(1.0 / 30.0)
    hub.record_sent(shapes=shapes, conf=0.95, packet_t=int(clock.now * 1000), proc_ms=proc_ms, now=clock.now)


class TestLifecycle:
    def test_initial_state_is_idle(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        snap = hub.snapshot()
        assert snap["status"] == STATUS_IDLE
        assert snap["engine"] == ""
        assert snap["packets_sent"] == 0
        assert snap["last_packet"] is None

    def test_begin_end_capture_transitions(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("mediapipe", "127.0.0.1", 11111)
        assert hub.snapshot()["status"] == STATUS_RUNNING
        hub.end_capture()
        snap = hub.snapshot()
        assert snap["status"] == STATUS_STOPPED
        # counters survive for the final report
        assert snap["engine"] == "mediapipe"

    def test_begin_capture_resets_counters(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("mediapipe", "127.0.0.1", 11111)
        _packet(hub, clock)
        assert hub.snapshot()["packets_sent"] == 1
        hub.record_send_error()
        assert hub.snapshot()["send_errors"] == 1
        hub.begin_capture("openseeface", "127.0.0.1", 11111)
        snap = hub.snapshot()
        assert snap["packets_sent"] == 0
        assert snap["send_errors"] == 0
        assert snap["last_packet"] is None
        assert snap["engine"] == "openseeface"

    def test_record_toggle(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.set_record(True, "session.jsonl")
        assert hub.snapshot()["record"] == {"active": True, "path": "session.jsonl"}
        hub.set_record(False)
        assert hub.snapshot()["record"] == {"active": False, "path": None}


class TestRates:
    def test_send_rate_over_window(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("mediapipe", "127.0.0.1", 11111)
        for _ in range(30):
            _packet(hub, clock)
        # 30 packets at ~30 Hz within the window -> close to 29.x fps
        rate = hub.send_rate(now=clock.now)
        assert 25.0 < rate < 31.0

    def test_rate_is_zero_with_single_packet(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        _packet(hub, clock)
        assert hub.send_rate(now=clock.now) == 0.0

    def test_old_samples_leave_the_window(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        _packet(hub, clock)
        clock.advance(RATE_WINDOW_S + 1.0)
        assert hub.send_rate(now=clock.now) == 0.0

    def test_fps_history_length_tracks_packets(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        for _ in range(10):
            _packet(hub, clock)
        snap = hub.snapshot()
        assert len(snap["fps_history"]) == 9  # one sample per consecutive pair
        assert len(snap["proc_ms_history"]) == 10


class TestChannels:
    def test_activity_is_latest_value_decayed(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        _packet(hub, clock, shapes={"jawOpen": 1.0})
        clock.advance(ACTIVITY_HALF_LIFE_S)
        _packet(hub, clock, shapes={"jawOpen": 0.0})
        channels = {c["name"]: c for c in hub.top_channels()}
        # latest value wins for value; activity decayed over dt = 1.0 + 1/30 s
        # (1.0 s explicit advance + the helper's own 1/30 s step)
        assert channels["jawOpen"]["value"] == 0.0
        assert channels["jawOpen"]["activity"] == pytest.approx(0.5 ** (1.0 + 1.0 / 30.0), rel=0.01)

    def test_top_channels_ordering_deterministic(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        _packet(hub, clock, shapes={"b": 0.9, "a": 0.9, "c": 0.2})
        names = [c["name"] for c in hub.top_channels()]
        assert names == ["a", "b", "c"]  # equal activity -> name ascending
        _packet(hub, clock, shapes={"c": 0.95})
        assert hub.top_channels()[0]["name"] == "c"

    def test_top_channels_respects_limit(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        shapes = {f"ch{i:02d}": i / 100 for i in range(20)}
        _packet(hub, clock, shapes=shapes)
        assert len(hub.top_channels(limit=5)) == 5


class TestBroadcastHub:
    def test_subscribe_publish_unsubscribe(self) -> None:
        hub = BroadcastHub()
        seen: list = []
        done = threading.Event()

        def on_snapshot(snapshot: dict) -> None:
            seen.append(snapshot)
            done.set()

        unsub = hub.subscribe(on_snapshot)
        hub.publish({"status": "running"})
        assert done.wait(timeout=2.0)
        assert seen == [{"status": "running"}]
        unsub()
        hub.publish({"status": "stopped"})
        assert len(seen) == 1

    def test_subscribe_is_idempotent(self) -> None:
        hub = BroadcastHub()
        count = {"n": 0}

        def on_snapshot(snapshot: dict) -> None:
            count["n"] += 1

        hub.subscribe(on_snapshot)
        hub.subscribe(on_snapshot)
        hub.publish({})
        assert count["n"] == 1

    def test_bad_subscriber_does_not_block_others(self) -> None:
        errors: list = []
        hub = BroadcastHub(on_subscriber_error=errors.append)
        good_seen: list = []
        good_done = threading.Event()

        def bad(_snapshot: dict) -> None:
            raise RuntimeError("boom")

        def good(_snapshot: dict) -> None:
            good_seen.append(_snapshot)
            good_done.set()

        hub.subscribe(bad)
        hub.subscribe(good)
        hub.publish({"ok": True})
        assert good_done.wait(timeout=2.0)
        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)

    def test_publish_from_many_threads(self) -> None:
        hub = BroadcastHub()
        received = {"n": 0}
        lock = threading.Lock()
        all_done = threading.Event()
        total = 20 * 5

        def on_snapshot(_snapshot: dict) -> None:
            with lock:
                received["n"] += 1
                if received["n"] == total:
                    all_done.set()

        hub.subscribe(on_snapshot)

        def worker() -> None:
            for _ in range(5):
                hub.publish({})

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5.0)
        assert all_done.wait(timeout=2.0)


class TestSnapshot:
    def test_snapshot_is_json_serializable(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("mediapipe", "127.0.0.1", 11111)
        hub.set_record(True, "s.jsonl")
        _packet(hub, clock)
        hub.record_send_error()
        snap = hub.snapshot()
        restored = json.loads(json.dumps(snap))
        assert restored["status"] == snap["status"]
        assert restored["udp"]["port"] == 11111
        assert restored["channels"][0]["name"]

    def test_snapshot_is_consistent_under_concurrency(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("mediapipe", "127.0.0.1", 11111)
        stop = threading.Event()
        errors: list = []

        def reader() -> None:
            while not stop.is_set():
                snap = hub.snapshot()
                if snap["packets_sent"] < 0:
                    errors.append("negative counter")

        thread = threading.Thread(target=reader)
        thread.start()
        for _ in range(200):
            _packet(hub, clock, proc_ms=0.1)
        stop.set()
        thread.join(timeout=5.0)
        assert errors == []
        assert hub.snapshot()["packets_sent"] == 200

    def test_proc_ms_stats(self, clock: FakeClock) -> None:
        hub = DashboardHub(clock=clock)
        hub.begin_capture("m", "h", 1)
        for proc in (1.0, 3.0, 2.0):
            _packet(hub, clock, proc_ms=proc)
        snap = hub.snapshot()
        assert snap["proc_ms_avg"] == pytest.approx(2.0)
        assert snap["proc_ms_max"] == pytest.approx(3.0)

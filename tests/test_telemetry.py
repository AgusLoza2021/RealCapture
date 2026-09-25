"""Unit tests for capture telemetry transport latency (pure logic, no bpy).

Clock-domain contract: ``packet.t`` is the sender's epoch-ms stamp; transport
latency must compare it against the applied time on the SAME epoch clock.
FPS stays on the monotonic clock. See docs/realcapture-tdd.md section 4.3.
"""

import time

import pytest

from addon.schema import Packet
from addon.telemetry import STATS_WINDOW, CaptureStats

VALID_POSE = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}
VALID_SHAPES = {"jawOpen": 0.5}


def make_packet(t: int) -> Packet:
    return Packet(
        t=t,
        engine="mediapipe",
        conf=0.97,
        pose=dict(VALID_POSE),
        shapes=dict(VALID_SHAPES),
    )


def test_live_path_reports_transport_latency_not_zero():
    """A packet stamped ~5 epoch-ms before application reports ~5 ms, not 0.0."""
    now = time.time()
    now_ms = int(now * 1000)
    packet = make_packet(t=now_ms - 5)
    stats = CaptureStats()
    # Live path: application time is taken on the monotonic clock; latency
    # must come from the epoch clock (default applied_epoch_ms = now), never
    # by subtracting packet.t from monotonic ms.
    stats.record_applied(packet, time.monotonic() * 1000.0)
    assert stats.max_transport_ms == pytest.approx(5.0, abs=3.0)
    assert stats.avg_transport_ms == pytest.approx(5.0, abs=3.0)


def test_explicit_epoch_stamp_is_used_for_latency():
    """An explicitly supplied applied epoch stamp is used for the difference."""
    now = time.time()
    now_ms = int(now * 1000)
    packet = make_packet(t=now_ms - 7)
    stats = CaptureStats()
    stats.record_applied(packet, time.monotonic() * 1000.0, float(now_ms))
    assert stats.max_transport_ms == pytest.approx(7.0, abs=0.5)
    assert stats.avg_transport_ms == pytest.approx(7.0, abs=0.5)


def test_negative_difference_is_clamped_to_zero():
    """A backwards clock jump (applied epoch before the send stamp) never goes negative."""
    now = time.time()
    now_ms = int(now * 1000)
    packet = make_packet(t=now_ms + 1000)
    stats = CaptureStats()
    stats.record_applied(packet, time.monotonic() * 1000.0, float(now_ms))
    assert stats.max_transport_ms == 0.0
    assert stats.avg_transport_ms == 0.0


def test_avg_max_over_rolling_window_and_reset():
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    for latency_ms in (1.0, 3.0, 5.0):
        stats.record_applied(
            make_packet(t=now_ms - int(latency_ms)),
            time.monotonic() * 1000.0,
            float(now_ms),
        )
    assert stats.avg_transport_ms == pytest.approx(3.0)
    assert stats.max_transport_ms == pytest.approx(5.0)

    # The window is rolling: only the newest STATS_WINDOW samples count.
    for i in range(STATS_WINDOW):
        stats.record_applied(
            make_packet(t=now_ms),
            time.monotonic() * 1000.0 + i,
            float(now_ms),
        )
    assert stats.max_transport_ms == pytest.approx(0.0)
    assert stats.packets_applied == 3 + STATS_WINDOW

    stats.reset()
    assert stats.avg_transport_ms == 0.0
    assert stats.max_transport_ms == 0.0
    assert stats.packets_applied == 0


def test_fps_still_uses_monotonic_clock():
    """FPS is a rate: it derives from monotonic spacing and ignores the epoch stamps."""
    stats = CaptureStats()
    base_mono = time.monotonic() * 1000.0
    now_ms = int(time.time() * 1000)
    # 5 packets applied 10 monotonic ms apart -> 4 intervals / 40 ms = 100 fps.
    for i in range(5):
        stats.record_applied(make_packet(t=now_ms - 500), base_mono + i * 10.0, float(now_ms))
    assert stats.applied_fps == pytest.approx(100.0, rel=0.01)


def test_replay_reports_zero_by_intent():
    """Replay passes the packet's own stamp as the applied epoch time: zero by intent."""
    packet = make_packet(t=int(time.time() * 1000))
    stats = CaptureStats()
    stats.record_applied(packet, time.monotonic() * 1000.0, float(packet.t))
    assert stats.max_transport_ms == 0.0
    assert stats.avg_transport_ms == 0.0
    assert stats.packets_applied == 1

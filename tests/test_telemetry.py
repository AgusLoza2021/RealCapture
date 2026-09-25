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


def test_negative_epoch_difference_clamps_without_erasing_positive_samples():
    """Property: a per-sample backwards epoch difference clamps to 0.0, but the
    clamp never erases real positive samples from the same session.

    Fails against an implementation that subtracts mismatched clocks: there,
    even the positive sample clamps to 0.0, so avg and max stay 0.0.
    """
    now = time.time()
    now_ms = int(now * 1000)
    stats = CaptureStats()
    # First: a real positive sample, 6 epoch-ms of transport latency.
    stats.record_applied(make_packet(t=now_ms - 6), time.monotonic() * 1000.0, float(now_ms))
    assert stats.max_transport_ms == pytest.approx(6.0, abs=0.5)
    # Then: a backwards clock jump (applied epoch 1000 ms before the send stamp).
    stats.record_applied(
        make_packet(t=now_ms + 1000), time.monotonic() * 1000.0, float(now_ms - 1000)
    )
    # The backwards sample clamps, but the earlier real sample survives.
    assert stats.max_transport_ms == pytest.approx(6.0, abs=0.5)
    assert stats.avg_transport_ms == pytest.approx(3.0, abs=0.5)
    assert stats.session_max_transport_ms == pytest.approx(6.0, abs=0.5)


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


def test_fps_uses_monotonic_clock_while_latency_uses_epoch_clock():
    """Property: the two clocks serve two purposes at once. FPS derives from
    monotonic spacing and ignores the epoch stamps, while the same calls must
    produce real epoch-based latency (not monotonic-minus-epoch clamped to 0)."""
    stats = CaptureStats()
    base_mono = time.monotonic() * 1000.0
    now_ms = int(time.time() * 1000)
    # 5 packets applied 10 monotonic ms apart -> 4 intervals / 40 ms = 100 fps.
    for i in range(5):
        stats.record_applied(make_packet(t=now_ms - 500), base_mono + i * 10.0, float(now_ms))
    assert stats.applied_fps == pytest.approx(100.0, rel=0.01)
    # Latency on the same samples comes from the epoch difference (~500 ms),
    # proving the monotonic FPS clock never leaks into the latency measurement.
    assert stats.avg_transport_ms == pytest.approx(500.0, abs=10.0)
    assert stats.max_transport_ms == pytest.approx(500.0, abs=10.0)
    assert stats.session_max_transport_ms == pytest.approx(500.0, abs=10.0)


def test_replay_zero_comes_from_stamp_not_clamping():
    """Property: replay latency is exactly zero because the applied epoch stamp
    equals the send stamp -- not because a mismatched clock clamped to 0.0.
    The same packet applied LATER must report the real difference."""
    now_ms = int(time.time() * 1000)
    packet = make_packet(t=now_ms)
    stats = CaptureStats()
    stats.record_applied(packet, time.monotonic() * 1000.0, float(packet.t))
    assert stats.max_transport_ms == 0.0
    assert stats.avg_transport_ms == 0.0
    assert stats.packets_applied == 1

    # Contrast case: same packet, applied 9 epoch-ms later -> real latency.
    later = CaptureStats()
    later.record_applied(packet, time.monotonic() * 1000.0, float(packet.t + 9))
    assert later.max_transport_ms == pytest.approx(9.0, abs=0.5)
    assert later.avg_transport_ms == pytest.approx(9.0, abs=0.5)
    assert later.session_max_transport_ms == pytest.approx(9.0, abs=0.5)


def test_session_max_spans_beyond_the_rolling_window():
    """Property: session_max_transport_ms keeps the maximum over EVERY sample,
    not just the last STATS_WINDOW, while max_transport_ms keeps rolling."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    # One 50 ms spike, then a full window of quiet 1 ms samples.
    stats.record_applied(make_packet(t=now_ms - 50), time.monotonic() * 1000.0, float(now_ms))
    for i in range(STATS_WINDOW):
        stats.record_applied(make_packet(t=now_ms - 1), time.monotonic() * 1000.0, float(now_ms))
    # The window has rolled past the spike...
    assert stats.max_transport_ms == pytest.approx(1.0, abs=0.5)
    # ...but the session max still remembers it.
    assert stats.session_max_transport_ms == pytest.approx(50.0, abs=0.5)


def test_session_max_resets_with_the_session():
    """Property: CaptureStats.reset() clears session_max_transport_ms too."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(make_packet(t=now_ms - 42), time.monotonic() * 1000.0, float(now_ms))
    assert stats.session_max_transport_ms > 0.0
    stats.reset()
    assert stats.session_max_transport_ms == 0.0
    assert stats.max_transport_ms == 0.0
    assert stats.avg_transport_ms == 0.0

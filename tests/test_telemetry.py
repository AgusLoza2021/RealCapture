"""Unit tests for capture telemetry transport latency (pure logic, no bpy).

Clock-domain contract: ``packet.t`` is the sender's epoch-ms stamp; transport
latency must compare it against the applied time on the SAME epoch clock.
FPS stays on the monotonic clock. See docs/realcapture-tdd.md section 4.3.
"""

import time

import pytest

from addon.schema import Packet
from addon.telemetry import (
    CAMERA_STATE_INVALID,
    CAMERA_STATE_MEASURED,
    CAMERA_STATE_MEASURED_INVALID,
    CAMERA_STATE_UNAVAILABLE,
    STATS_WINDOW,
    CaptureStats,
    camera_latency_state,
)

VALID_POSE = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}
VALID_SHAPES = {"jawOpen": 0.5}


def make_packet(t: int, extra: dict | None = None) -> Packet:
    return Packet(
        t=t,
        engine="mediapipe",
        conf=0.97,
        pose=dict(VALID_POSE),
        shapes=dict(VALID_SHAPES),
        extra=dict(extra) if extra else {},
    )


def make_stamped_packet(t: int, acq_t_ms: int) -> Packet:
    return make_packet(t, {"acq_t_ms": acq_t_ms})


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


def test_record_invalid_default_count_is_one():
    """record_invalid() keeps its zero-argument call shape, with count as an
    optional delta for consumers feeding cumulative counters."""
    stats = CaptureStats()
    stats.record_invalid()
    assert stats.invalid_packets == 1
    stats.record_invalid(3)
    assert stats.invalid_packets == 4
    stats.reset()
    assert stats.invalid_packets == 0


def test_record_stale_dropped_counts_and_resets():
    """record_stale_dropped accumulates dropped-stale packets and reset clears it."""
    stats = CaptureStats()
    stats.record_stale_dropped()
    stats.record_stale_dropped(4)
    assert stats.packets_dropped_stale == 5
    stats.reset()
    assert stats.packets_dropped_stale == 0


def test_session_max_gap_tracks_spike_beyond_the_window():
    """Property: session_max_gap_ms keeps the largest gap between two
    consecutive applied packets on the monotonic clock, outside the rolling
    window: a full STATS_WINDOW of quiet samples must not erase the spike."""
    stats = CaptureStats()
    base = 1_000_000.0
    # Two applied packets 1500 monotonic ms apart, then a full window of
    # quiet 10 ms samples so the deque rolls past the spike entirely.
    stats.record_applied(make_packet(t=1), base, 1.0)
    stats.record_applied(make_packet(t=2), base + 1500.0, 2.0)
    for i in range(STATS_WINDOW):
        stats.record_applied(make_packet(t=3), base + 1500.0 + (i + 1) * 10.0, 3.0)
    assert stats.session_max_gap_ms == pytest.approx(1500.0)


def test_session_max_gap_ignores_first_packet_and_resets():
    """The first applied packet has no predecessor: no gap is recorded."""
    stats = CaptureStats()
    base = 2_000_000.0
    stats.record_applied(make_packet(t=1), base, 1.0)
    assert stats.session_max_gap_ms == 0.0
    stats.record_applied(make_packet(t=2), base + 20.0, 2.0)
    assert stats.session_max_gap_ms == pytest.approx(20.0)
    stats.reset()
    assert stats.session_max_gap_ms == 0.0


# ---------------------------------------------------------------------------
# Camera-to-rig acquisition latency (fail-closed telemetry, feature T2).
#
# Contract: the ONLY camera timing source is ``packet.extra["acq_t_ms"]``.
# A usable stamp is an integer (not bool), positive, not later than
# ``packet.t`` and not later than the applied epoch ms. Missing stamp -> the
# camera metric stays explicitly unavailable (None), never a healthy 0.0.
# Present-but-unusable stamps -> counted as invalid, never aggregated.
# ---------------------------------------------------------------------------


def test_valid_camera_stamp_produces_latency_and_counts_sample():
    """A valid stamp 40 epoch-ms before application reports ~40 ms camera latency."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 40),
        time.monotonic() * 1000.0,
        float(now_ms),
    )
    assert stats.camera_samples == 1
    assert stats.avg_camera_ms == pytest.approx(40.0, abs=0.5)
    assert stats.max_camera_ms == pytest.approx(40.0, abs=0.5)
    assert stats.session_max_camera_ms == pytest.approx(40.0, abs=0.5)
    assert stats.missing_acq_stamps == 0
    assert stats.invalid_acq_stamps == 0
    state, _text = camera_latency_state(stats)
    assert state == CAMERA_STATE_MEASURED


def test_camera_stamp_equal_to_applied_time_is_a_valid_zero_sample():
    """acq == applied is a legitimate measured 0.0 sample, not unavailable."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms), time.monotonic() * 1000.0, float(now_ms)
    )
    assert stats.camera_samples == 1
    assert stats.avg_camera_ms == 0.0
    state, _text = camera_latency_state(stats)
    assert state == CAMERA_STATE_MEASURED


def test_absent_stamp_key_is_missing_not_invalid_and_packet_still_counts():
    """A packet WITHOUT the acq_t_ms key is missing: it counts in the explicit
    missing counter, keeps camera latency unavailable (None), and never
    touches invalid stamps or transport telemetry."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_packet(now_ms), time.monotonic() * 1000.0, float(now_ms)
    )
    assert stats.camera_samples == 0
    assert stats.missing_acq_stamps == 1
    assert stats.invalid_acq_stamps == 0
    assert stats.avg_camera_ms is None
    assert stats.max_camera_ms is None
    assert stats.session_max_camera_ms is None
    # The packet itself was applied and its transport latency recorded.
    assert stats.packets_applied == 1
    assert stats.max_transport_ms >= 0.0
    state, _text = camera_latency_state(stats)
    assert state == CAMERA_STATE_UNAVAILABLE


def test_all_missing_packets_report_the_missing_count_as_unavailable():
    """Every applied packet without the key increments missing_acq_stamps; the
    unavailable text must name that count, not look like a measured value."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    for _ in range(3):
        stats.record_applied(make_packet(now_ms), time.monotonic() * 1000.0, float(now_ms))
    assert stats.missing_acq_stamps == 3
    assert stats.camera_samples == 0
    assert stats.avg_camera_ms is None
    state, text = camera_latency_state(stats)
    assert state == CAMERA_STATE_UNAVAILABLE
    assert "3" in text, "the missing stamp count must be visible"


def test_fresh_state_says_no_samples_yet_and_never_implies_measured_zero():
    stats = CaptureStats()
    assert stats.camera_samples == 0
    assert stats.missing_acq_stamps == 0
    assert stats.avg_camera_ms is None
    state, text = camera_latency_state(stats)
    assert state == CAMERA_STATE_UNAVAILABLE
    assert "no samples yet" in text


def test_missing_stamp_beside_valid_ones_is_measured_and_reports_missing():
    """One valid + one stamp-less packet: measured values retained, missing
    count visible, no error state (missing is not invalid)."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 30), time.monotonic() * 1000.0, float(now_ms)
    )
    stats.record_applied(make_packet(now_ms), time.monotonic() * 1000.0, float(now_ms))
    assert stats.camera_samples == 1
    assert stats.missing_acq_stamps == 1
    assert stats.invalid_acq_stamps == 0
    assert stats.avg_camera_ms == pytest.approx(30.0, abs=0.5)
    state, text = camera_latency_state(stats)
    assert state == CAMERA_STATE_MEASURED
    assert "1" in text, "the missing stamp count must stay visible"


@pytest.mark.parametrize(
    "extra",
    [
        {"acq_t_ms": "1700000000000"},  # string, not an integer
        {"acq_t_ms": 1_700_000_000_000.0},  # float, not an integer
        {"acq_t_ms": True},  # bool masquerading as int
        {"acq_t_ms": None},  # present null: no usable integer stamp
        {"acq_t_ms": 0},  # non-positive
        {"acq_t_ms": -5},  # negative epoch ms
    ],
)
def test_unusable_stamp_classes_count_invalid_and_never_aggregate(extra):
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_packet(now_ms, extra), time.monotonic() * 1000.0, float(now_ms)
    )
    assert stats.camera_samples == 0
    assert stats.avg_camera_ms is None
    assert stats.max_camera_ms is None
    assert stats.session_max_camera_ms is None
    assert stats.invalid_acq_stamps == 1
    # The packet itself stays applied with valid transport telemetry.
    assert stats.packets_applied == 1
    state, _text = camera_latency_state(stats)
    assert state == CAMERA_STATE_INVALID


def test_null_stamp_value_is_invalid_not_missing():
    """A PRESENT acq_t_ms = None is not key absence: it is an unusable stamp,
    counted as invalid, never as missing."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_packet(now_ms, {"acq_t_ms": None}), time.monotonic() * 1000.0, float(now_ms)
    )
    assert stats.camera_samples == 0
    assert stats.invalid_acq_stamps == 1
    assert stats.missing_acq_stamps == 0
    state, _text = camera_latency_state(stats)
    assert state == CAMERA_STATE_INVALID


def test_stamp_after_applied_time_is_invalid_by_the_applied_bound():
    """Discriminating: the stamp respects the send bound (acq <= packet.t) but
    lies AFTER the applied epoch ms. Only the applied-time bound can reject
    this stamp; removing that bound makes the sample valid and fails this test.
    Fixed epochs keep it deterministic."""
    send_ms = 1_000_000
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(send_ms, send_ms),  # acq == send: send bound passes
        5_000.0,
        999_999.0,  # applied BEFORE the acquisition stamp
    )
    assert stats.camera_samples == 0
    assert stats.invalid_acq_stamps == 1
    assert stats.avg_camera_ms is None


def test_stamp_after_send_time_is_invalid_by_the_send_bound():
    """Discriminating: the stamp is BEFORE the applied epoch ms (applied bound
    alone would accept it) but AFTER packet.t, breaking causality. Only the
    send bound can reject it; removing that bound makes the sample valid."""
    send_ms = 1_000_000
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(send_ms, send_ms + 1),  # acq > send: send bound fails
        5_000.0,
        1_000_002.0,  # applied after the stamp: applied bound would pass
    )
    assert stats.camera_samples == 0
    assert stats.invalid_acq_stamps == 1
    assert stats.avg_camera_ms is None


def test_mixed_valid_and_invalid_keeps_measured_values_and_counts_invalid():
    """Invalid stamps never poison the aggregates but stay visible."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 20), time.monotonic() * 1000.0, float(now_ms)
    )
    stats.record_applied(
        make_packet(now_ms, {"acq_t_ms": "bogus"}),
        time.monotonic() * 1000.0,
        float(now_ms),
    )
    stats.record_applied(
        make_packet(now_ms, {"acq_t_ms": -1}),
        time.monotonic() * 1000.0,
        float(now_ms),
    )
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 40), time.monotonic() * 1000.0, float(now_ms)
    )
    assert stats.camera_samples == 2
    assert stats.invalid_acq_stamps == 2
    assert stats.missing_acq_stamps == 0
    assert stats.avg_camera_ms == pytest.approx(30.0, abs=0.5)
    assert stats.max_camera_ms == pytest.approx(40.0, abs=0.5)
    state, text = camera_latency_state(stats)
    assert state == CAMERA_STATE_MEASURED_INVALID, "valid+invalid must be an error state"
    assert "30" in text and "40" in text, "measured values must be retained"
    assert "2" in text, "the invalid stamp count must stay visible"


def test_camera_window_rolls_but_session_max_keeps_the_spike():
    """max_camera_ms is rolling; session_max_camera_ms spans EVERY sample."""
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 90), time.monotonic() * 1000.0, float(now_ms)
    )
    for _ in range(STATS_WINDOW):
        stats.record_applied(
            make_stamped_packet(now_ms, now_ms - 3),
            time.monotonic() * 1000.0,
            float(now_ms),
        )
    assert stats.max_camera_ms == pytest.approx(3.0, abs=0.5)
    assert stats.session_max_camera_ms == pytest.approx(90.0, abs=0.5)
    assert stats.camera_samples == 1 + STATS_WINDOW


def test_reset_clears_every_camera_counter_and_window():
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 15), time.monotonic() * 1000.0, float(now_ms)
    )
    stats.record_applied(make_packet(now_ms), time.monotonic() * 1000.0, float(now_ms))
    stats.record_applied(
        make_packet(now_ms, {"acq_t_ms": "bad"}),
        time.monotonic() * 1000.0,
        float(now_ms),
    )
    assert stats.missing_acq_stamps == 1
    assert stats.invalid_acq_stamps == 1
    stats.reset()
    assert stats.camera_samples == 0
    assert stats.missing_acq_stamps == 0
    assert stats.invalid_acq_stamps == 0
    assert stats.avg_camera_ms is None
    assert stats.max_camera_ms is None
    assert stats.session_max_camera_ms is None
    state, text = camera_latency_state(stats)
    assert state == CAMERA_STATE_UNAVAILABLE
    assert "no samples yet" in text


def test_camera_stamp_leaves_transport_telemetry_unchanged():
    """The same packet with and without the stamp must produce identical
    transport telemetry: the new metric never perturbs the old one."""
    now_ms = int(time.time() * 1000)
    mono = time.monotonic() * 1000.0
    with_stamp = CaptureStats()
    with_stamp.record_applied(
        make_stamped_packet(now_ms, now_ms - 40), mono, float(now_ms)
    )
    without_stamp = CaptureStats()
    without_stamp.record_applied(make_packet(now_ms), mono, float(now_ms))
    assert with_stamp.avg_transport_ms == pytest.approx(without_stamp.avg_transport_ms)
    assert with_stamp.max_transport_ms == pytest.approx(without_stamp.max_transport_ms)
    assert with_stamp.session_max_transport_ms == pytest.approx(
        without_stamp.session_max_transport_ms
    )
    assert with_stamp.packets_applied == without_stamp.packets_applied
    assert with_stamp.applied_fps == pytest.approx(without_stamp.applied_fps)


def test_camera_state_text_reports_values_and_session_max():
    now_ms = int(time.time() * 1000)
    stats = CaptureStats()
    stats.record_applied(
        make_stamped_packet(now_ms, now_ms - 25), time.monotonic() * 1000.0, float(now_ms)
    )
    state, text = camera_latency_state(stats)
    assert state == CAMERA_STATE_MEASURED
    assert "25" in text, "the measured average must be rendered"
    assert "session" in text.lower(), "the session max must be rendered"

"""Unit tests for the pure soak gate logic (no bpy, no argv, no I/O).

Contract: ``evaluate_soak_gates(report)`` returns a list of failure messages;
an empty list means the run passes. Beyond the original checks (applied floor
derived from ``minutes``, invalid packets, session lines vs applied), three
properties are pinned here:

- liveness: a transport latency of exactly zero is a dead measurement, not a
  fast one, so it must fail;
- session coverage: the session-wide max is gated, so a spike outside the
  rolling 120-sample window cannot hide;
- positive control: with an ``expected_latency_floor_ms`` in the report, a
  measurement that did not respond to the injected stamp skew must fail.
"""

from __future__ import annotations

from tools.soak_gates import evaluate_soak_gates


def passing_report() -> dict:
    """A report shape that must pass every gate (mirrors blender_soak output)."""
    applied = 30 * 60 * 30  # 30 minutes at a 30 Hz average
    return {
        "minutes": 30.0,
        "port": 11111,
        "packets_applied": applied,
        "applied_fps": 30.0,
        "transport_avg_ms": 9.1,
        "transport_max_ms": 18.0,
        "session_max_transport_ms": 18.0,
        "invalid_packets": 0,
        "session_lines": applied,
        "tick_p95_ms": 1.5,
        "engine": "soak",
    }


def test_passing_report_has_no_failures():
    """A healthy soak report passes every gate."""
    assert evaluate_soak_gates(passing_report()) == []


def test_applied_below_25fps_floor_fails():
    """Fewer applied packets than minutes * 60 * 25 fails the applied floor."""
    report = passing_report()
    report["packets_applied"] = 1000
    failures = evaluate_soak_gates(report)
    assert len(failures) == 1
    assert "below 25 fps average" in failures[0]


def test_invalid_packets_fail():
    """Any invalid packet fails the run."""
    report = passing_report()
    report["invalid_packets"] = 3
    failures = evaluate_soak_gates(report)
    assert failures == ["3 invalid packets"]


def test_lost_session_lines_fail():
    """Session lines far below applied packets means the recording lost packets."""
    report = passing_report()
    report["session_lines"] = 100
    failures = evaluate_soak_gates(report)
    assert len(failures) == 1
    assert "session recording lost packets" in failures[0]


def test_windowed_transport_max_over_100_fails():
    """The original windowed max gate still applies over 100 ms."""
    report = passing_report()
    report["transport_max_ms"] = 120.0
    report["session_max_transport_ms"] = 120.0
    failures = evaluate_soak_gates(report)
    assert any("transport max 120.0 ms > 100 ms" in f for f in failures)


def test_zero_average_latency_is_dead_not_fast():
    """Property (liveness): an average of exactly 0.0 is a dead measurement.

    This is the regression that survived M1: a clamped constant 0.0 used to
    present as a perfect latency. The session max is deliberately left healthy,
    so the average check is the only possible source of this failure; asserting
    only on the word "dead" would also be satisfied by the session-max message.
    """
    report = passing_report()
    report["transport_avg_ms"] = 0.0
    failures = evaluate_soak_gates(report)
    assert failures, "a zero average latency must not pass the gate"
    assert any("average transport latency" in f for f in failures), failures
    assert any("dead" in f for f in failures), failures


def test_zero_session_max_latency_is_dead_not_fast():
    """Property (liveness): a session-wide max of exactly 0.0 fails the gate.

    The windowed average is left healthy so only the session check can fire.
    """
    report = passing_report()
    report["session_max_transport_ms"] = 0.0
    failures = evaluate_soak_gates(report)
    assert failures, "a zero session max latency must not pass the gate"
    assert any("session max transport latency" in f for f in failures), failures


def test_liveness_is_aggregate_not_per_sample():
    """Property (liveness): only an aggregate of exactly 0.0 counts as dead.

    Differential on purpose, so the test cannot be satisfied by a gate that
    always returns no failures: the all-zero report MUST fail, while a mixed
    report with individual zero samples MUST pass.
    """
    all_dead = passing_report()
    all_dead["transport_avg_ms"] = 0.0
    all_dead["session_max_transport_ms"] = 0.0
    assert evaluate_soak_gates(all_dead), "an all-zero report must fail the gate"

    mixed = passing_report()
    mixed["transport_avg_ms"] = 2.5
    mixed["session_max_transport_ms"] = 12.0
    assert evaluate_soak_gates(mixed) == []


def test_missing_session_max_key_fails():
    """Property (session coverage): a report without session_max_transport_ms
    cannot prove session-wide coverage and must fail."""
    report = passing_report()
    del report["session_max_transport_ms"]
    failures = evaluate_soak_gates(report)
    assert failures, "a report lacking session_max_transport_ms must not pass"
    assert any("session_max_transport_ms" in f for f in failures), failures


def test_session_max_over_100_fails_even_when_window_is_clean():
    """Property (session coverage): a spike outside the rolling window is
    caught by the session-wide max even when the windowed max looks healthy."""
    report = passing_report()
    report["transport_max_ms"] = 18.0  # window shows nothing wrong
    report["session_max_transport_ms"] = 250.0  # minute-5 spike
    failures = evaluate_soak_gates(report)
    assert failures, "a session-wide spike must not pass just because the window is clean"
    assert any("250.0" in f and "100" in f for f in failures), failures


def test_session_max_at_100_exactly_passes():
    """Boundary: 100.0 ms is at the limit, not over it."""
    report = passing_report()
    report["session_max_transport_ms"] = 100.0
    assert evaluate_soak_gates(report) == []


def test_positive_control_fails_when_measurement_does_not_respond():
    """Property (positive control): with an expected latency floor, an average
    below 80% of it means the measurement ignored the injected skew."""
    report = passing_report()
    report["expected_latency_floor_ms"] = 40
    report["transport_avg_ms"] = 5.0
    report["session_max_transport_ms"] = 6.0
    failures = evaluate_soak_gates(report)
    assert failures, "a measurement stuck below the injected floor must fail"
    assert any("did not respond" in f or "injected" in f for f in failures), failures


def test_positive_control_passes_at_80_percent_of_floor():
    """Boundary: an average at exactly 80% of the floor satisfies the control."""
    report = passing_report()
    report["expected_latency_floor_ms"] = 40
    report["transport_avg_ms"] = 32.0  # 0.8 * 40
    assert evaluate_soak_gates(report) == []


def test_positive_control_skipped_when_floor_absent():
    """Without an expected floor (plain run), no positive-control check runs."""
    report = passing_report()
    report["transport_avg_ms"] = 0.5  # low but alive
    assert evaluate_soak_gates(report) == []

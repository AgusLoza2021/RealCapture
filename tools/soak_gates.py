"""Pure soak gate evaluation (no bpy, no argv, no I/O).

Extracted from the inline gate block at the end of ``tools/blender_soak.py``'s
``main()`` so it can be unit-tested. ``evaluate_soak_gates`` receives the soak
report dict and returns failure messages; an empty list means the run passes.

Beyond the original checks (applied floor derived from ``minutes``, windowed
transport max, invalid packets, session lines vs applied), the gates close
three holes that survived milestone M1, where a clamped constant 0.0 latency
always passed:

- liveness: an aggregate latency of exactly 0.0 is a dead measurement, not a
  fast one;
- session coverage: the session-wide maximum is gated, so a spike outside the
  rolling window cannot hide;
- stall coverage: the session-wide apply gap is gated (missing field fails as
  unmeasured; over 500 ms fails), so a stall that the average fps floor hides
  cannot pass;
- throttle vs loss: the stale-drop ratio is gated, since stale discards are
  frames lost to queue pressure, not to a slow consumer;
- positive control: when the report carries an ``expected_latency_floor_ms``
  (injected stamp skew), an average below 80% of that floor proves the
  measurement did not respond to the injection.
"""

from __future__ import annotations


def evaluate_soak_gates(report: dict) -> list[str]:
    """Evaluate the soak report against every quality gate.

    Returns failure messages (empty list means pass). Pure: reads the report
    dict only, no bpy, no argv, no I/O.
    """
    failures: list[str] = []

    applied = report.get("packets_applied", 0)
    minutes = report.get("minutes", 0.0)
    if applied < minutes * 60 * 25:  # < 25 fps average
        failures.append(f"applied {applied} packets is below 25 fps average")

    windowed_max = report.get("transport_max_ms", 0.0)
    if windowed_max > 100:
        failures.append(f"transport max {windowed_max:.1f} ms > 100 ms")

    if report.get("invalid_packets", 0) > 0:
        failures.append(f"{report['invalid_packets']} invalid packets")

    session_lines = report.get("session_lines", 0)
    if session_lines < applied * 0.9:
        failures.append("session recording lost packets")

    # Hole 2: session-wide latency coverage. A report without the field cannot
    # prove the whole session was measured, so it must fail.
    if "session_max_transport_ms" not in report:
        failures.append(
            "soak report lacks session_max_transport_ms; session-wide latency is unmeasured"
        )
    else:
        session_max = report["session_max_transport_ms"]
        if session_max > 100:
            failures.append(f"session transport max {session_max:.1f} ms > 100 ms")

    # Hole 2b: session-wide stall coverage. A report without the field cannot
    # prove the whole session's inter-apply gaps were measured, so it must
    # fail. 500 ms is 15 missed frames at 30 Hz: a stall the average fps
    # floor is computed over the whole run cannot see.
    if "session_max_gap_ms" not in report:
        failures.append(
            "soak report lacks session_max_gap_ms; session-wide apply gap is unmeasured"
        )
    else:
        gap = report["session_max_gap_ms"]
        if gap > 500:
            failures.append(
                f"session-wide apply gap {gap:.1f} ms > 500 ms "
                "(15 missed frames at 30 Hz)"
            )

    # Throttle vs loss: stale discards are real frame loss from queue
    # pressure. The ratio gate keeps it under 1% of drained traffic.
    stale = report.get("stale_dropped", 0)
    drained = stale + report.get("packets_applied", 0)
    stale_ratio = stale / drained if drained else 0.0
    if stale_ratio > 0.01:
        failures.append(
            f"stale drop ratio {stale_ratio:.4f} ({stale} stale drops) > 0.01"
        )

    # Hole 1: liveness. A measurement that reports exactly zero (or negative)
    # on its aggregates is dead, not fast. A single zero sample does not trip
    # this: the aggregates only hit 0.0 when no real latency was measured.
    avg = report.get("transport_avg_ms", report.get("avg_transport_ms", 0.0))
    if avg <= 0.0:
        failures.append(
            f"average transport latency {avg:.1f} ms: the measurement looks dead, not fast"
        )
    if "session_max_transport_ms" in report and report["session_max_transport_ms"] <= 0.0:
        failures.append(
            f"session max transport latency {report['session_max_transport_ms']:.1f} ms: "
            "the measurement looks dead, not fast"
        )

    # Hole 3: positive control. Only asserted when the run injected a known
    # stamp skew; a measurement stuck at a constant cannot satisfy it.
    floor = report.get("expected_latency_floor_ms")
    if floor is not None and avg < floor * 0.8:
        failures.append(
            f"average transport latency {avg:.1f} ms did not respond to the injected "
            f"stamp skew (expected at least {floor * 0.8:.1f} ms)"
        )

    return failures

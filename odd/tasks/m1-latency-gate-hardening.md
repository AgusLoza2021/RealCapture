# Feature: M1 latency gate hardening — make the measurement impossible to fake

Status: **queued (proposed) — not authorized for implementation.** The owner parked this on
2026-09-25 to be picked up later in this repository after the closure work landed.
Branch: none yet. Create it when this is picked up.
TDD: RED-first. Runner: `python -m pytest tests/ -q`; Blender 4.5 headless for the soak.

## Why this exists

M1's latency gate (`tools/blender_soak.py:130`, `if stats.max_transport_ms > 100:`)
**could not fail** for the entire duration of M1. `addon/telemetry.py` compared the sender's
epoch-ms stamp against the receiver's monotonic clock, so `max(0.0, ...)` clamped every
sample to exactly `0.0`, and the gate tested that constant. The recorded claim "transport
max < 100 ms" was validated against a number that could never be anything else.

The clock domain was fixed on 2026-09-25 and real latency was measured for the first time
(avg 9.11 ms / max 17.97 ms over UDP loopback). The gate now receives real data — but it is
still **shaped** so that this exact class of failure can pass again. That is what this
feature closes. Full forensic detail and file/line evidence:
`odd/tasks/milestone-closure-m0-m1.md`.

## The three surviving holes (all confirmed by independent verification)

1. **No lower bound.** `max_transport_ms > 100` passes on a constant `0.0`. A future
   re-clamp — the precise defect that survived all of M1 — sails through.
2. **The gate reads a rolling window, not the session.** `max_transport_ms` is the maximum of
   a 120-sample deque (`addon/telemetry.py`), i.e. roughly the last 4 seconds at 30 Hz. A
   latency spike at minute 5 of a 30-minute run is not gated at all.
3. **No positive control.** Every assertion that only bounds a value from above can drift
   back to a fake pass. Only an assertion that *requires the number to move* cannot.

## Tasks

| id | Task | Status |
|---|---|---|
| T1 | Add the missing lower bound to the soak gate: treat `max_transport_ms <= 0.0` (and `avg_transport_ms <= 0.0`) as a gate FAILURE with an explicit message, so a dead measurement can never present as healthy. | not started |
| T2 | Track a **session-wide** max latency in `CaptureStats` and gate on that, keeping the rolling window for the UI panel where it belongs. A 30-minute gate must be able to see minute 5. | not started |
| T3 | Add a positive control: a synthetic pre-send delay option to `tools/soak_send.py` (for example `--delay-ms N`), plus a test/soak variant asserting the reported average rises by approximately `N`. A measurement stuck at a constant cannot satisfy this. This is the strongest of the three. | not started |
| T4 | Make the new telemetry tests discriminating. Independent verification found only 3 of the 6 tests in `tests/test_telemetry.py` actually fail against a verbatim pre-fix formula; the other three pass under the old formula and fail only on the signature change. Fix the three, and record which test proves which property. | not started |
| T5 | Prove the whole thing once: run the soak with and without the positive control and show the gate failing for a real reason (for example `--delay-ms 150` must trip the `> 100 ms` gate). Record both reports. | blocked on T1–T3 |

## Evidence to produce

- Soak report showing non-zero, non-constant latency with the session-wide max.
- A demonstrated gate FAILURE under an injected delay: the gate must be shown failing for a
  real reason, not merely passing.
- A test listing that names which test proves which property.

## Constraints and non-goals

- **No wire or schema change.** `t` stays an epoch-ms integer, and `addon/schema.py` stays
  byte-identical to `backend/common/packets.py` (`tests/test_schema_sync.py` pins it).
- **Tests must keep running without mediapipe installed**: pure-logic tests only, heavy
  dependencies stay import-guarded.
- **No new dependencies.**
- **Do not redefine the M1 exit criterion here.** The camera-and-inference segment (which the
  criterion names and this metric structurally cannot see, because `t` is stamped after
  inference) is an owner decision, tracked in `odd/tasks/milestone-closure-m0-m1.md`.
- **No drive-by refactors** of the telemetry, consumer, or soak test beyond these gates.
- No commit, push, or PR without explicit owner authorization.

# Feature: M1 latency gate hardening — make the measurement impossible to fake

Status: **delivered 2026-09-25** — implemented, then independently verified with real soak runs.
Evidence below. Branch: `m1-latency-closure`.
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
| T1 | Add the missing lower bound to the soak gate: treat `max_transport_ms <= 0.0` (and `avg_transport_ms <= 0.0`) as a gate FAILURE with an explicit message, so a dead measurement can never present as healthy. | done — fails on `avg` and on `session_max`, message says "looks dead, not fast" |
| T2 | Track a **session-wide** max latency in `CaptureStats` and gate on that, keeping the rolling window for the UI panel where it belongs. A 30-minute gate must be able to see minute 5. | done — `session_max_transport_ms`, reset in `reset()`; a missing key fails closed |
| T3 | Add a positive control: a synthetic pre-send delay option to `tools/soak_send.py` (for example `--delay-ms N`), plus a test/soak variant asserting the reported average rises by approximately `N`. A measurement stuck at a constant cannot satisfy this. This is the strongest of the three. | done as `--stamp-skew-ms N`, a stamp skew instead of a sleep: a sleep would drop the rate and trip the 25 fps gate for the wrong reason |
| T4 | Make the new telemetry tests discriminating. Independent verification found only 3 of the 6 tests in `tests/test_telemetry.py` actually fail against a verbatim pre-fix formula; the other three pass under the old formula and fail only on the signature change. Fix the three, and record which test proves which property. | done — the three strengthened tests fail against the pre-fix clock on assertions, not on the signature |
| T5 | Prove the whole thing once: run the soak with and without the positive control and show the gate failing for a real reason (for example `--delay-ms 150` must trip the `> 100 ms` gate). Record both reports. | done — clean run passes; a 150 ms skew is measured at avg 158.1 ms and the gate exits 1 |

## Evidence

Gate logic extracted to `tools/soak_gates.py` so the gates are testable without Blender
(`evaluate_soak_gates(report) -> list[str]`, pure: no bpy, no argv, no I/O).

**RED** — `python -m pytest tests/test_soak_gates.py tests/test_telemetry.py -q`:
`ModuleNotFoundError: No module named 'tools.soak_gates'` plus 5 failures against the unlocked
implementation (`AttributeError: 'CaptureStats' object has no attribute
'session_max_transport_ms'`). Discriminating-power check on the three strengthened tests,
replaying the verbatim pre-fix formula `max(0.0, monotonic_ms - packet.t)`: measured 0.0 where
6.0 / 500.0 / 9.0 were required — they fail for the stated reason, not on arity.

**GREEN** — same command: 22 passed. Full suite: `python -m pytest tests/ -q` ->
**158 passed** (baseline 142).

**Independent verification** (separate agent, read-only on source, live Blender runs):

| Run | Command | Result |
|---|---|---|
| Clean | `blender -b --python tools/blender_soak.py -- 2 11111` | exit 0, `SOAK GATES PASSED`, avg 9.42 ms, session max 19.08 ms, 3,598 packets, 0 invalid |
| Positive control | sender `--stamp-skew-ms 150`, runner `-- 2 11111 120` | **exit 1**, `SOAK GATE FAILED: transport max 167.2 ms > 100 ms` and `session transport max 168.3 ms > 100 ms`; avg 158.13 ms |

The 150 ms skew shows up as 158.13 - 150 = 8.13 ms of real transport against 9.42 ms clean:
the injected latency lands in the measurement within loopback noise, and the gate fails for a
latency reason while the packet-rate gate keeps passing. Feeding the synthetic old behaviour
(`avg 0.0`, `session_max 0.0`) to the gate returns two "measurement looks dead" failures, and
the archived pre-fix report now fails the gate as well. Mutation testing of the gate module
(10 mutants: each gate dropped, plus the 100 ms boundary) was killed by at least one test in
every case; two weak tests found by that pass were tightened afterwards so each now kills the
mutant it names. Pre-existing evidence remains byte-identical
(`soak_output/soak_report_30min_pre_fix.json` and its 24 MB session file).

## Surviving ways a dead measurement could still pass (recorded, not hidden)

1. **Intermittent death** — a measurement that dies only for some samples, leaving one
   non-zero sample in the last 120, passes (5000 forced zeros plus one real 1 ms sample
   returns no failures).
2. **Non-zero-constant death** — emitting a plausible constant such as 5.0 ms passes when no
   expected floor is injected. The positive control is the guard, and it is opt-in.
3. **The positive control is self-reported** — the floor comes from the same report and only
exists when the third argument is passed, so default soak runs still have no independent
   oracle for latency. It is a control, not an oracle.

## Evidence to produce

All produced; see the Evidence section above.

## Constraints and non-goals

- **No wire or schema change.** `t` stays an epoch-ms integer, and `addon/schema.py` stays
  byte-identical to `backend/common/packets.py` (`tests/test_schema_sync.py` pins it). The
  skew flag changes the *value* of a stamp in a test sender, never the schema.
- **Tests must keep running without mediapipe installed**: pure-logic tests only, heavy
  dependencies stay import-guarded. The gate module is bpy-free by design.
- **No new dependencies.**
- **Do not redefine the M1 exit criterion here.** The camera-and-inference segment (which the
  criterion names and this metric structurally cannot see, because `t` is stamped after
  inference) is an owner decision, tracked in `odd/tasks/milestone-closure-m0-m1.md`.
- **No drive-by refactors** of the telemetry, consumer, or soak test beyond these gates.
- No commit, push, or PR without explicit owner authorization.

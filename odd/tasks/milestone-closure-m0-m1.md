# Feature: M0/M1 closure — reconcile the roadmap with reality, and make latency measurable

Status: in progress — owner authorized 2026-09-25 ("ejecutá la primera")
Branch: none yet (working tree on `main`). Commits pending explicit owner authorization.
TDD: RED-first for the telemetry defect. Runner: `python -m pytest tests/ -q`;
Blender 4.5 headless for the transport measurement.

**Delivered 2026-09-25:** T1–T5 (roadmap reconciled, defect fixed under RED-first, real
measurement produced, status set honestly), plus the M0 README stub. **Still open and
owner-owned:** T6 (full 30-minute re-run on the fixed code) and T9 (choose the measurement
point for the camera + inference segment, or reword the criterion). **T7 and T8 landed and
were verified in their own feature doc**, `odd/tasks/m1-latency-gate-hardening.md`: the gate is
no longer vacuous (it exits 1 on a real 158 ms measurement), and the weak tests it exposed are
tightened.

## Goal

Close M0 and M1 honestly, so M2 can start without violating the roadmap's own rule
("no milestone starts before the previous one's exit criteria are met"). Exploration
showed the gap is not bookkeeping: M1's exit criterion was never measured, because the
telemetry that was supposed to measure it returns a constant `0.0`.

## What exploration established (verified, with file/line evidence)

### The roadmap is behind the work, not ahead of it

| Claim in `docs/roadmap.md` | Reality per `odd/tasks/` | Evidence |
|---|---|---|
| M0 `In progress`, "Git repository initialized, M0 committed" unchecked (line 10) | done | `odd/tasks/realcapture-plan.md`: commit `cefe2a0` |
| M0 "Public README stub" unchecked | genuinely open — there is no root `README.md` | `ls README*` finds nothing at the repo root |
| M1 `Open`, all six items unchecked (line 20) | A–F all `[x]` | `odd/tasks/m1-stabilization.md`, commits `eff08f4`, `2cc9d57`, `0f9dd87`, `f59567d`, `45ebb74` |
| M1 exit: "end-to-end latency measured ≤ 60 ms" | **not measured** — see the defect below | `soak_output/soak_report.json` |

### The defect: the latency telemetry compares two different clocks

1. The wire field `t` is **epoch milliseconds**:
   - `backend/backends/mediapipe_backend.py:184` → `t=int(time.time() * 1000)`
   - `tools/soak_send.py:93` → `t_ms = int(time.time() * 1000)`
   - `docs/realcapture-tdd.md:73` shows the contract by example: `"t": 1718345678901`
   - `addon/session.py:5-8` records `recv_t` as epoch ms for the same reason
2. The receiver compares it against a **monotonic** clock:
   - `addon/consumer.py:126` → `now_ms = time.monotonic() * 1000.0`, passed into
     `self.stats.record_applied(packet, now_ms)` in the live path
   - `addon/telemetry.py:37` → `transport_ms = max(0.0, applied_monotonic_ms - packet.t)`
3. `epoch_ms - monotonic_ms` is a large **negative** number (monotonic is milliseconds
   since boot; epoch is ~1.79e12), so `max(0.0, ...)` clamps it to **exactly 0.0** for
   every packet.
4. Consequence in the product: `addon/ui.py:141` renders
   `Transport: avg {avg_transport_ms:.1f} ms / max {max_transport_ms:.1f} ms`, so the
   operator panel has always shown `0.0 ms / 0.0 ms`.
5. Consequence in the evidence: `soak_output/soak_report.json` reports
   `"transport_avg_ms": 0.0, "transport_max_ms": 0.0` alongside
   `"packets_applied": 53415`. A 30-minute run over real UDP with 53,415 packets applied
   that reports exactly `0.0` for both average and maximum is not a measurement; it is
   the clamp.
6. Nothing caught it: `grep -rn "transport_ms\|CaptureStats\|record_applied" tests/`
   returns **zero matches**. The suite passes with the defect present.
7. The module docstring actively misleads: `addon/telemetry.py:1-6` states that
   `packet.t` is the backend's epoch-ms timestamp and that "values are clamped to >= 0
   anyway". That sentence is what makes a broken measurement read like a design decision.

The replay path is *not* a defect: `addon/consumer.py` passes `float(packet.t)` for
replay, so the subtraction is legitimately zero. That intent is correct; it must survive
the fix.

## Authorized scope (owner decisions, 2026-09-25)

| Decision | Choice |
|---|---|
| Scope | Reconcile M0/M1 in `docs/roadmap.md` against real evidence, and fix the telemetry defect so the exit criterion becomes measurable |
| Which side is wrong | The **receiver**. The wire contract stays epoch ms: `t` is the public seam (§4.3), and session replay depends on absolute time |
| Measurement | Headless Blender run over the real UDP transport, with the measured segment labelled precisely |
| Delivery | Docs are updated by the orchestrator; the code fix goes to a delegated writer; no commit without explicit authorization |

## Explicit non-goals

- **No wire or schema change.** `t` stays an epoch-ms integer, `KNOWN_TOP_LEVEL_FIELDS`
  stays closed, and `addon/schema.py` stays byte-identical to `backend/common/packets.py`
  (`tests/test_schema_sync.py` enforces it).
- **No new dependency.**
- **No claim that the headless measurement covers camera capture or engine inference.**
  It covers transport + consumer apply with a synthetic sender. The full path still needs
  a live camera session with the owner, and the milestone text must say so.
- **No re-run of the full 30-minute soak unless the owner asks for it.** The measurement
  needs steady state, not duration.
- **No private solver work.** This feature touches public surface only.
- **No roadmap status that claims more than the evidence holds.**

## Design of the fix

Two clocks, two purposes, named explicitly instead of inferred:

- **FPS** is a rate: it must stay on the monotonic clock (`_applied_times`).
- **Latency** is a difference against a sender-supplied wall-clock stamp: it must use the
  epoch clock on both sides.

`CaptureStats.record_applied` therefore takes both, and the replay path keeps passing the
packet's own stamp so replay still reports zero deliberately rather than by accident.

## Tasks

| id | Task | Status |
|---|---|---|
| T1 | Write `docs/roadmap.md` M0/M1 against the evidence above | done 2026-09-25 |
| T2 | RED test for the live latency path, the replay path, and the clamp behaviour | done 2026-09-25 |
| T3 | Fix the clock domain in `addon/telemetry.py` + `addon/consumer.py`; correct the misleading docstring | done 2026-09-25 |
| T4 | Headless Blender measurement over the real UDP transport; record the labelled segment | done 2026-09-25 |
| T5 | Record evidence here and set the M1 status honestly | done 2026-09-25 |
| T6 | (owner decision) re-run the full 30-minute soak for the closure record | not started |
| T7 | Make the soak latency gate non-vacuous: lower bound + a session-wide max instead of the 120-sample window | done — `odd/tasks/m1-latency-gate-hardening.md`, verified: gate exits 1 at avg 158.1 ms / session max 168.3 ms |
| T8 | Strengthen `tests/test_telemetry.py` so each test is discriminating for the clock-domain fix (see finding 1) | done — the three tests now fail against the pre-fix clock on assertions, not on arity |
| T9 | (owner decision) choose the measurement point for the camera + inference segment, or reword the M1 criterion | blocked on owner |

## Evidence

### T1 — roadmap reconciled (2026-09-25)
`docs/roadmap.md`: M0 → the git/commit item closed against `cefe2a0` (verified with
`git log --oneline cefe2a0 -1` → "docs: add TDD v0.1, roadmap (M0-M5), and capture-landscape
research"), status kept at `In progress`; M1 → all six items `[x]` with verified commit
references (`eff08f4`, `0f9dd87`, `2cc9d57`, `f59567d`), status `Open` → `In progress`.
Both sections now carry the drift notes, and the two-open-milestones rule conflict is
recorded rather than hidden.

### T2/T3 — the defect fixed under RED-first (2026-09-25)
- RED: `python -m pytest tests/test_telemetry.py -v` → **6 failed**. The load-bearing failure
  is the defect itself: `assert 0.0 == 5.0 ± 3` — a packet stamped 5 ms before its applied
  epoch time reported `0.0`. The other five failed on
  `TypeError: CaptureStats.record_applied() takes from 2 to 3 positional arguments but 4 were given`.
- GREEN: same command → **6 passed in 0.03s**.
- No regression: `python -m pytest tests/ -q` → **142 passed, 1 warning in 5.86s**
  (136 before + 6 new; the warning is a pre-existing Starlette deprecation from the FastAPI
  testclient, unrelated).
- Files: `addon/telemetry.py` (two-clock `record_applied`, corrected docstring),
  `addon/consumer.py` (both `_apply` call sites, replay intent made explicit),
  `tests/test_telemetry.py` (new, dependency-free).
- The only callers of `record_applied` in the repository are the two `_apply` branches in
  `addon/consumer.py`; both updated. Independently confirmed by the verifier with
  `grep -rn record_applied`.

### T4 — real measurement over UDP (2026-09-25)
Independent verifier run. Blender exit status **0**, `SOAK GATES PASSED`.

| | pre-fix (30 min) | post-fix (3 min) |
|---|---|---|
| packets applied | 53,415 | 5,400 |
| avg transport ms | **0.0** | **9.11** |
| max transport ms | **0.0** | **17.97** |
| invalid packets | 0 | 0 |
| applied fps | 29.98 | 29.98 |

Sender log: `packets=7201 elapsed=240.0s rate=30.00 Hz send_errors=0`. Soak log:
`[01:00] applied=1801 fps=30.1 transport avg=8.8ms max=17.3ms invalid=0`,
`[02:00] applied=3600 fps=29.9 transport avg=9.3ms max=18.0ms invalid=0`. The pre-fix
30-minute baseline is preserved at `soak_output/soak_report_30min_pre_fix.json` (that
directory is gitignored, as is its 24 MB session counterpart the verifier also preserved).

**What the number is:** transport + consumer apply over UDP loopback with a synthetic sender
(`engine: "soak"`). **What it is not:** it excludes camera capture and engine inference —
`t` is stamped after inference (`backend/backends/mediapipe_backend.py:184`). It is not a
webcam-to-Blender figure, and it must never be quoted as one.

### T5 — honest status (2026-09-25)
M1 keeps `In progress`. Two of its three exit criteria now hold on evidence (30-minute soak
clean; telemetry visible). The latency criterion stays open for a reason the numbers
themselves expose: the metric cannot see the segment the criterion names.

### Findings from independent verification that are NOT yet fixed
1. **Only 3 of the 6 new tests prove the fix.** Replaying them against a verbatim pre-fix
   formula (arity-tolerant) fails only `test_live_path_reports_transport_latency_not_zero`,
   `test_explicit_epoch_stamp_is_used_for_latency`, and
   `test_avg_max_over_rolling_window_and_reset`. The other three pass under the old formula
   and fail only on the signature change. They are still useful; they are not evidence of the
   clock-domain fix. (T8)
2. **The soak latency gate is still vacuous in one direction.** `max_transport_ms > 100` has
   no lower bound, so a future re-clamp to `0.0` passes again — the same class of failure that
   survived all of M1. (T7)
3. **The gate reads a rolling window, not the session.** `max_transport_ms` is the maximum of
   a 120-sample deque, i.e. the last ~4 s at 30 Hz. A spike at minute 5 of a 30-minute run is
   not gated at all. (T7)
4. **No positive control exists.** The only assertion that cannot silently drift back is a
   synthetic pre-send delay in `tools/soak_send.py`, with the reported average required to
   rise by approximately that delay. (T7)

### Explicitly not verified here
- No visual confirmation of the Blender UI panel render (`addon/ui.py:141`): background mode
  never draws it. The non-zero field values plus the formatting code are the evidence.
- No full 30-minute run on the fixed code (T6, owner decision).

## Evidence

Filled in as each task closes. Nothing is claimed here that was not observed.

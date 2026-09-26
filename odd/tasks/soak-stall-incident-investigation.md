# Feature: Soak stall incident — what happened in the 30-minute run

Status: **open defect, reported 2026-09-25. Cause NOT established, but the classification IS.**
Forensic re-analysis of the preserved artifacts was run 2026-09-26 (independent, read-only) and
narrowed the phenomenon to a host-or-process freeze; it also **corrected one of this document's own
counts** and designed the one experiment that separates the two remaining hypotheses. See "Forensic
classification" below. One incident in one run.
Needs a reproduction run and a discriminating run. Nothing committed.

**Naming note:** the cause is *not* known to be transport. The link is UDP over loopback with no
network path, so any delay lives in kernel socket buffers or in process scheduling. This doc
therefore says **stall incident**, not "transport incident", and the independent audit below
explicitly refuted the transport label.

## The incident

The first 30-minute soak with the hardened gate in place failed:

```
SOAK GATE FAILED: session transport max 2359.8 ms > 100 ms
BLENDER_EXIT=1
```

Artifacts (`soak_output/` is gitignored):

| File | Size | What it is |
|---|---|---|
| `soak_output/soak30_post_fix.log` | 3,112 B | run log with every per-minute line |
| `soak_output/soak_report_30min_post_fix.json` | 433 B | machine-readable report |
| `soak_output/soak_session_30min_post_fix.jsonl` | 24,331,455 B | 52,863 recorded frames: the per-packet evidence |

## Timeline, reconstructed per packet from `recv_t - packet.t`

Not one event but **three localized latency clusters** in an otherwise clean run:

| Window | Behaviour |
|---|---|
| t = 0 – 78 s | nominal: 30.0/s, everything under 50 ms |
| t = **80.4 – 117.1 s** | **the main incident.** 23 samples above 100 ms, peak **2,359 ms** at t=91.0 s; receive-loop gaps to **3,191 ms**; minute 2 applies only **740** frames (12.3 fps) |
| t = **167.5 – 169.8 s** | a second, much smaller cluster: 5 samples of 56–94 ms |
| t = **1,325.8 – 1,338.7 s** | a third cluster: 9 samples of 51–82 ms, plus one **159 ms** sample at t=1,339.8 s; minute 23 applies 1,743 frames |
| everything else | 30.0/s, under 50 ms |

Totals: **47 samples above 50 ms** (31 inside the main incident, 16 outside), 24 above 100 ms
(23 inside, 1 outside), 8 above 1 s, 3 above 2 s. Three minutes contain every sample above
50 ms. Two minutes run below the nominal 1,800 frames: minute 2 (740) and minute 23 (1,743).
The run applied 52,863 frames over 1,800 s = 29.37/s, i.e. **1,137 fewer than the sender's
nominal 30/s**; **1,025 of them (90 %) are inside the main incident window**.

## Why the previous gate could not have caught it

The old gate read `max_transport_ms`, the maximum of a 120-sample deque — about the last four
seconds. At report time that value was **17.71 ms**, so it would have passed. The session-wide
max is **2,359.8 ms**. This is exactly the hole the hardening closed
(`odd/tasks/m1-latency-gate-hardening.md`), demonstrated on the first long run after it shipped.

## It is not an artefact of the new metric

The pre-fix 30-minute session file, recomputed packet by packet the same way, is clean: 53,415
samples, 29.99/s, latency avg **8.77 ms**, max **18.00 ms**, **zero** samples above 50 ms (p95
16 ms, p99 17 ms), largest receive gap **338 ms**. The incident is not normal behaviour of the
pipeline and not something the clock fix introduced.

## The two stall signatures (keep them apart)

The first version of this doc got this wrong, and the independent audit caught it.

1. **Receiver stalled, sender alive** — large `recv_t` gap, small `packet.t` gap at the same
   index, and a stale apply. Examples: idx 2421 (`drecv` 618 ms / `dt` 15 ms / latency 616 ms),
   idx 2450 (734 / 22 / 712), idx 2414 (435 / 46 / 402). This is the Blender main thread not
   polling.
2. **Sender silent** — large `packet.t` gap, an almost equally large `recv_t` gap, and a
   **near-zero** latency: nothing arrived for 0.3–1.9 s with no backlog to drain. Examples:
   idx 2388 (329 / 344 / latency 1→16 ms), idx 2400 (745 / 731 / 14→0), idx 2441 (1923 / 1947 /
   3→27). This is the sender process not being scheduled.

**What is NOT a stall:** a large `packet.t` gap with a *small* `recv_t` gap and a huge preceding
latency (idx 2395, 2398, 2422, 2431, 2451). That is **backlog drain**: ~2.5 s of sender stamps
sitting in the socket buffer being drained in ~169 ms of wall time. It proves the sender never
stopped. The 2,516 ms "sender stamp gap" is this drain artefact, not sender silence.

## Established

- **Latest-frame-wins is by design.** `addon/receiver.py` drains up to 64 datagrams per poll and
  decodes only the newest, silently discarding stale frames — "for facial animation, an old frame
  is worse than a dropped frame". The 1,025 in-window missing frames are discards, not
  corruption; the 2,359 ms figure is the honest end-to-end latency of the newest frame at that
  moment.
- **The incident is host-side, not network-side.** The link is loopback UDP; there is no network
  path that can carry a 2.4 s delay. Sender silence is directly measurable in the artifacts, so
  CPU/scheduling contention is established for signature 2. Receiver-side stalls are consistent
  with our own receive path (see hypothesis 2).
- **Both the app and the host are in scope.** Signature 1 points at our loop, signature 2 at the
  host.

## Not established — hypotheses, ranked

1. **Host contention** (CPU starvation, disk writeback, Defender scanning the 24 MB session file,
   power state). Directly evidenced for signature 2.
2. **Session recording inside the receive path.** `SessionRecorder.record()` writes one JSON line
   per applied frame and flushes every 60 packets (`addon/session.py`), and the soak enables it
   (`tools/blender_soak.py:51-52`). A blocking flush in a 60 Hz pump loop would look exactly like
   signature 1. **Not yet discriminated from the host.**
3. UDP receive-buffer overflow — the mechanism of the loss, not necessarily of the stall.

## Impact if it is real

For 37 seconds in a 30-minute session the rig would receive frames up to 2.4 s late and lose
about 1,025 of them — a frozen or stuttering face. Nothing in the project would have reported it
before this run.

## A second vacuous metric found while auditing this run

`CaptureStats.record_invalid()` (`addon/telemetry.py:64`) **is never called anywhere in
`addon/` or `tools/`**, and `UdpReceiver.invalid_count` is incremented and asserted in tests but
**never read by `addon/consumer.py`**. Therefore:

- `stats.invalid_packets` is structurally always `0`;
- the gate line `tools/soak_gates.py:41` (`invalid_packets > 0`) can never fire;
- `addon/ui.py:142-143` can never render the "Invalid packets" line.

This is the same family of defect as the original latency bug: **a check that cannot fail.** It
also means every historical "0 invalid" figure — including the M1 evidence rows in
`docs/roadmap.md` — is uninformative rather than reassuring.

## Reproduction evidence from the verification run (2026-09-25)

The independent verifier ran a 2-minute soak on this machine, on an otherwise idle host:

```
[01:00] applied=1800 fps=30.0 transport avg=9.6ms max=18.0ms dropped=0 gap_max=63.0ms invalid=0
session_max_transport_ms: 328.6    session_max_gap_ms: 312.0
stale_dropped: 9    stale_drop_ratio: 0.0025    idle_polls: 3451
SOAK GATE FAILED: session transport max 328.6 ms > 100 ms
```

The failure is on the **pre-existing** 100 ms session bound, not on the new gates (gap 312 ≤ 500,
ratio 0.0025 ≤ 0.01). One ~300 ms in-tick stall at t+90.1 s. The session file's own `recv_t` gap
is 315 ms while its latency never exceeds 28 ms, because `recv_t` is stamped **before** the apply
work and `session_max_transport_ms` is sampled **after** it — so the two "session max" figures are
taken at different instants inside the same tick. Anyone reconciling the report against
`soak_session.jsonl` will see that ~300 ms discrepancy and must not read it as a bug.

**Consequence for M1:** this host currently fails the 100 ms session bound even on a clean 2-minute
run, so "30-minute soak clean" is not achievable here until the stall itself is addressed or the
bound is made host-aware. That is now part of the M1 measurement-point decision, not a separate
question.

**Consequence for the hypothesis ranking:** recording was **enabled** in all three runs, and the
pre-fix 30-minute run was clean with it enabled. Session-recorder I/O is therefore not a sufficient
cause. The stall coincides with the Blender apply path and with host scheduling.

## Gate gaps this run exposed

1. **No drop counter**, and the invalid counter is dead (above), so the gate cannot tell
   throttling from loss.
2. **The 25 fps floor is a whole-run average.** Minute 2 ran at 12.3 fps and passed.
3. The positive control is still opt-in; see `odd/tasks/m1-latency-gate-hardening.md`.

## Forensic classification (2026-09-26, independent read-only re-analysis)

Every aggregate below was rebuilt from the preserved JSONL by hand and the method was validated by
reproducing this document's own cluster-2 numbers exactly (5 samples, 56/69/69/94/67 ms). Doc index =
JSONL line − 2 (line 1 is the header).

**Signature classification, which is the real advance.** Per recorded line: `G_r` = `recv_t` gap,
`G_t` = `packet.t` gap, `L` = `recv_t − packet.t`.

- **(c) receiver stall** (`G_r ≫ G_t`, `L ≳ 0.8·G_r`) — **dominant.** Pure: 1157/246/1155,
  1988/137/1865, 1329/139/1201, **2449/104/2359 (the peak)**, 435/46/402, 618/15/616, 734/22/712 ms.
  c-dominant or mixed: 3191/1156/2036 and four more. ≈12 of the 31 elevated samples.
- **(b) sender silence / arrival hole** (`G_t ≈ G_r` large, `L` small) — **real but secondary.** Pure:
  745/731/0, 398/397/1, 1947/1923/27 ms; plus burst-and-hole samples. ≈10 samples.
- **(a) strict backlog drain** (`L ≥ G_r`) — **zero confirmed.** All 30 stale applies have `L < G_r`,
  so in no sample did the applied frame arrive before the previous apply. The ~2.5 s apparent "stamp
gaps" are sender-side holes followed by catch-up bursts (`G_t > G_r`), **not** a queue holding 2.5 s of
stamps. This confirms and generalises the document's original separation of the two signatures: the
backlog drain is still not a stall.
- Mixed samples exist where `G_t` **and** `G_r` are both large (1830/1873, 2468/1089, 3191/1156) —
  sender and receiver froze *together*. That is the strongest single clue and it points away from our
  receive loop.

**`packet.t` is not a 33.3 ms grid.** `t` is `int(time.time()*1000)` stamped at send time, so the
observed diffs are real: 12, 18, 21, 25, 29, 34, 41, 54, 78 ms in healthy regions. The *intended*
schedule is a grid; the stamps are not. A harness artefact is also confirmed: `phase` derives from
`time.monotonic()`, quantised to **1/64 s = 15.625 ms** on this host, and is sampled *before* the
sleep, so payload values repeat and lag real time by up to ~47 ms. This does not affect `t`-based
latency, but it does degrade soak payload realism.

**No periodicity.** Cluster onsets 80.4 s → 167.5 s → 1325.8 s give intervals of 87.1 s and 1158.3 s:
no 60 s or 300 s period. Sub-episodes inside the main incident recur at ~2–2.7 s, which is close to
the recorder flush cadence (60 packets ≈ 2 s) — a candidate coupling, explicitly **not** a proof.

**The peak tick cannot be an apply-cost spike.** `recv_t` is stamped *before* `face_points.apply()`
(`addon/consumer.py:157` vs `:160`). At the peak tick, JSONL `L` = 2359 ms while the post-apply
`session_max_transport_ms` is 2359.795 ms, i.e. property writes + record + flush + apply cost roughly
**≤ 2 ms** on that tick. The 2.36 s elapsed *before* `recv_t`.

**The recorder-flush hypothesis is refuted as the dominant cause.** Minute 1 applies ~1800 packets
(~30 flushes) with a maximum of ≤ 22 ms; the incident window has ≤ 2 flushes but ~30 sub-episodes;
the applied-packet-2400 flush lands at t ≈ 80.0 s in **both** runs and is benign in the clean pre-fix
run (`L` = 11 ms). Recording was enabled in both runs. Same for a fixed kernel socket buffer: the
capacity implied by `L = G_r − C·33 ms` varies from 0.06 to 35 frames, so no single buffer explains
it, and a pure burst cannot produce `L ≈ 2.4 s` (that would require `L ≥ G_r`, never observed).
Clock mis-attribution is excluded too: latency returns to a 0–30 ms baseline after every cluster and
there is no step in the offset.

**Correction to this document — cluster 3.** The timeline above says 9 samples of 51–82 ms. On
exhaustive re-read, cluster 3 contains **4 samples in [52, 67] ms** (62, 67, 55, 52) **plus one
159 ms** sample whose signature is cleanly (c) (`G_r` 183, `G_t` 48). The original count of 9 is not
reproducible from the preserved file. Two few-hundred-millisecond windows inside that range were not
read exhaustively, so 4 + 1 is a floor, not necessarily the exact total — but the "9 samples 51–82 ms"
figure must not be quoted. **The headline totals are unaffected**: 47 × >50 ms, 24 × >100 ms, 8 × >1 s,
3 × >2 s, and 1,025 of the 1,137 missing frames (90 %) still fall inside the main incident.

**Ranked hypotheses after the analysis.** (1) Host-wide multi-second deschedule — CPU starvation,
paging, EcoQoS throttling, AV scan: supported by the simultaneous `G_t`/`G_r` freeze, by the stall
reproducing on an idle host in 2 minutes, and by host state being the only difference from the clean
pre-fix run. (2) A Blender-process-only stall: supported by (c) dominating with `t` still advancing,
but it cannot explain genuine sender silence. (3) Sender-side scheduling and harness defect:
explains every `t`-hole and burst, cannot create a 2449 ms receiver gap alone. (4) Recorder flush /
AV scan of the 24 MB JSONL: **refuted as dominant**, a rare AV freeze not fully excluded.

**The one decisive experiment (designed, NOT run).** Run the same UDP workload into a **plain-Python
receiver** alongside an **external host-freeze probe**, same host, same 30-minute window. If the
plain-Python receiver also logs >100 ms gaps coincident with freezer lines, it is host-wide; if it
stays under 50 ms while Blender stalls in the same window, it is Blender-specific, and only then does
an in-Blender record-on/record-off A/B plus an in-process liveness thread make sense. This was
deliberately not run during the analysis, because a concurrent Blender workload would have made the
latency evidence invalid.

**Additional code defects found by the analysis** (beyond the dead invalid counter and the two blind
spots already recorded): `addon/receiver.py:32-37` never sets `SO_RCVBUF`, so the receive buffer is
the Windows default; `addon/receiver.py:53-58` catches only `BlockingIOError` in the drain loop, so a
`ConnectionResetError`/`OSError` on Windows would escape into the soak handler; `DEFAULT_MAX_DRAIN =
64` silently caps how much backlog one poll may clear; `addon/session.py:62` calls `flush()` with **no
`fsync` anywhere in the repository**; the soak report stores `tick_p95_ms` but **no tick max**, so the
per-tick apply-cost distribution is not recoverable from any preserved artifact; and
`tools/blender_soak.py:79-87` pumps at a measured ~57.5 Hz with a `behind` value that is computed and
never used, so there is no catch-up.

## Tasks

| id | Task | Depends on |
|---|---|---|
| T1 | **Reproduce or refute. DONE, and the reproduction is cheap.** A 2-minute verification run on 2026-09-25 hit a ~300 ms in-tick stall at t+90 s: `session_max_gap_ms` 312.0, `session_max_transport_ms` 328.6, 9 stale discards, 0 errors. The stall class therefore reproduces in 2 minutes, not 30, and there is now a cheap loop. **Still open:** its frequency across N runs. | none |
| T2 | **Narrowed 2026-09-26, superseded by T9.** One 30-minute run with `settings.record_session = False`, one with it enabled, same host and load. The forensic re-analysis already refutes the recorder flush as the **dominant** cause (minute 1 = ~30 flushes at ≤ 22 ms; the incident window has ≤ 2 flushes but ~30 sub-episodes; the coincident flush is benign in the clean run), so this A/B is now a confirmation step inside T9 rather than the discriminator. | T1 |
| T3 | **DONE 2026-09-25.** `UdpReceiver.stale_dropped` + `reset_counters()`; `CaptureStats.packets_dropped_stale` and `record_stale_dropped()`; `record_invalid(count=1)` now actually called by the consumer via tracked deltas; report keys `stale_dropped`, `stale_drop_ratio`, `idle_polls`, `session_max_gap_ms`; UI row. 173 tests pass (baseline 158). | none |
| T4 | **DONE 2026-09-25.** Gate fails on a missing `session_max_gap_ms` ("unmeasured"), on `session_max_gap_ms > 500`, and on `stale_drop_ratio > 0.01`. Independently verified: the preserved failed 30-minute run derives a 3,191 ms max gap and **fails**; the clean pre-fix run derives 338 ms and **passes**. No pre-existing check was tightened or removed. | T3 |
| T5 | Decide from T1/T2: if it is our loop, move session writes off the receive path; if it is the host, record it as an environmental limit with the evidence and keep the gate. | T1, T2 |
| T6 | Correct the M1 record: state whether the 30-minute exit criterion is met on evidence, with the incident frequency, and drop the now-uninformative "0 invalid" claims. | T5 |

| T7 | **Calibrate the two new bounds.** The 500 ms gap bound has only ~1.6× headroom over healthy data (312 ms observed on a clean 2-minute run), and `stale_drop_ratio` is not run-length-normalized, so a short run fails on the same absolute jitter that a long run tolerates. Decide: raise the bound, aggregate over a window, or normalize by run length. **Intensified 2026-09-26: the forensic analysis found host-wide multi-second freezes are the leading explanation, which makes a fixed absolute 500 ms bound the wrong shape of gate for this host.** | T3 |
| T8 | **Close the two remaining blind spots the verification found:** `session_max_gap_ms` cannot see a stall on the final applied packet, and `tick_p95_ms` is reported but not gated at all. | T4 |
| T9 | **Run the one decisive experiment** designed by the 2026-09-26 forensic analysis: the same UDP workload into a plain-Python receiver plus an external host-freeze probe, same host and window. It separates a host-wide freeze from a Blender-process stall in a single run, and it must **not** be run concurrently with any Blender work or the evidence is invalid. | T1 |
| T10 | **Fix the additional code defects the forensic analysis found:** no `SO_RCVBUF` (`addon/receiver.py:32-37`), the drain catches only `BlockingIOError` (`:53-58`), the silent `DEFAULT_MAX_DRAIN = 64` cap, `flush()` without `fsync` (`addon/session.py:62`), no tick-max in the soak report, the dead `behind` and ~57.5 Hz pump in `tools/blender_soak.py:79-87`, and the pre-sleep, 15.625 ms-quantised `phase` in `tools/soak_send.py`. | none |

## Non-goals

- **No change to latest-frame-wins.** Dropping stale frames is right for facial animation.
- **No wire or schema change.** `addon/schema.py` stays byte-identical to
  `backend/common/packets.py`; no sequence numbers. `packet.t` gaps already infer loss offline.
- **No causality claim before T2.**
- No new dependencies, and no changes to the synthetic smoke test.
- No commit, push, or PR without explicit owner authorization.

## Evidence

- Run: 2026-09-25, wall 1,800.04 s, Blender 4.5.2 LTS, exit 1 from the gate (not a crash: the
  message is built at `tools/soak_gates.py:56-57` and prefixed at `tools/blender_soak.py:140`).
- Hashes, all four recomputed and matching: pre-fix report
  `cab012ecc0283436d4afc69ae5baea3f1e2e06909f67dee1d4c5444ac4e07257`, pre-fix session
  `49a26b9f6029b78d3af6e9be627e7bfb54080ddc1f21d7c890dd94fa3fe83f87`, post-fix report
  `b65582bfb1ac0071792dbfb217108d1ded00004a203c964e0c76d6f82a05bdaa`, post-fix session
  `105fd5f4f524d7303f16f8c65c250410df88b6b61cf829bb15101e5a1aa74bcc`.
- **Independent artifact audit, 2026-09-25** (separate verifier, read-only, no soak): confirmed
  claims 3–8 (per-minute counts, the 1,137/1,025 shortfall, the clean pre-fix baseline, that the
  old gate would have passed at 17.71 ms, the exit-1 provenance, and the latest-frame-wins
  discards); **refuted** "one incident only" (two further clusters), **refuted** the "alternating
  sender/receiver stalls" reading (drain catch-up was mislabelled as sender silence), and
  **refuted** the transport label. It also found the dead invalid counter independently.
  `python -m pytest tests/ -q` → 158 passed.
- Honest gap: **the pre-fix 30-minute run's own log was not preserved.** `soak30.log` is the
  post-fix log and `soak_run.log` is a 3-minute run; only the pre-fix *report* and *session file*
  survive. Session data is the stronger evidence, but the gap is recorded rather than glossed.
- Succession: the first delegated verifier stalled on its 30-minute limit and returned nothing,
  so the initial analysis was produced directly by the orchestrator and then independently
  audited, which is what corrected the interpretation above.

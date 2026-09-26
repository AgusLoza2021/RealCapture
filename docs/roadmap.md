# RealCapture — Roadmap

Status line per milestone: `Open` → `In progress` → `Done (date)`.
Rules: one milestone active at a time; no milestone starts before the previous one's exit criteria are met; every milestone closes with reviewable work-unit commits.

**Locked decisions:** Windows-first local phase · Blender 4.2 LTS floor · MediaPipe + OpenSeeFace backends · local-first, open-source later.

---

## M0 — Documentation & Project Skeleton — `In progress`
- [x] Research pass 1 (fidelity, latency, rig compat, landscape)
- [x] Research pass 2 (capture-engine repos + license audit)
- [x] TDD v0.1
- [ ] Roadmap reviewed by author
- [x] Git repository initialized, M0 committed — `cefe2a0`
- [x] Public README stub (positioning + IP note, no methodology) — `README.md`, added 2026-09-25; points at this roadmap as the single status source instead of restating milestone states

**Exit criteria:** docs reviewed; repo has M0 commit.

> **Rule conflict surfaced 2026-09-25 (recorded, not hidden).** M1's implementation is
> complete while M0 is still open, which violates "no milestone starts before the previous
> one's exit criteria are met". Of M0's two open items, the README stub is now written;
> what remains is one owner action (`Roadmap reviewed by author`). Completing that closes
> M0 and restores the rule instead of weakening it.

## M1 — Stabilization Harness — `In progress`
Goal: trustworthy plumbing before feature work.
- [x] Capture backend runner as external process (both engines), own venv — `eff08f4`, `0f9dd87`
- [x] UDP/JSON transport, latest-frame-wins receiver in `bpy.app.timers` (30–60 Hz) — `2cc9d57`
- [x] Per-stage latency telemetry (overlay/panel) + session log — `2cc9d57`, `f59567d`
- [x] Epsilon gating + property write path (controller object + native drivers) — `2cc9d57`
- [x] Session record/replay of packet streams — `f59567d`
- [ ] Stability soak test: 30+ min live session, no degradation, no crash — the original run was clean on its recorded data (53,415 applied @ 29.98 fps, latency max 18.0 ms), but the first re-run under a live gate **failed**: a 37-second stall incident from t=80 s to t=117 s, peak 2.36 s, ~1,025 frames dropped, plus two smaller clusters. Cause **not established** (host contention vs our receive loop) — `odd/tasks/soak-stall-incident-investigation.md`

**Exit criteria:** end-to-end latency measured ≤ 60 ms on reference scene; 30-min soak clean; telemetry visible.

> **Latency criterion — measurable as of 2026-09-25, not yet met.** The telemetry meant to
> evidence it was broken: `addon/telemetry.py` compared the sender's epoch-ms stamp against
> the receiver's monotonic clock, so `max(0.0, ...)` clamped every sample to exactly `0.0`.
> The panel always read `0.0 ms / 0.0 ms`, and the soak gate `tools/blender_soak.py:130`
> (`max_transport_ms > 100`) could not fail — the recorded "transport max < 100 ms" claim was
> validated against that constant. Fixed the same day (epoch on both sides); re-measured over
> real UDP: **avg 9.1 ms / max 18.0 ms**, 5,400 packets, 0 invalid. That figure covers
> transport + consumer apply only: the `t` stamp is taken *after* engine inference, so camera
> capture and inference are excluded from this metric by construction. The "reference scene"
> number this criterion names therefore still has no measurement point; choosing one (a stamp
> at frame grab, or an external end-to-end observer) is an open owner decision.
>
> Hardened 2026-09-25 so the same class of failure cannot pass again: the gate logic moved to
> the pure, unit-testable `tools/soak_gates.py`; it now fails on a zero (dead) measurement, on
> the **session-wide** latency max rather than a 120-sample window, and on an opt-in positive
> control (`tools/soak_send.py --stamp-skew-ms` plus an expected floor argument). Demonstrated
> both ways on real runs: clean run passes at avg 9.4 ms / session max 19.1 ms, and a 150 ms
> injected skew is measured as avg 158.1 ms, failing the gate with exit 1. The previously
> recorded pre-fix report now fails the gate instead of passing it.
> Details and follow-ups: `odd/tasks/milestone-closure-m0-m1.md`,
> `odd/tasks/m1-latency-gate-hardening.md`.
>
> **First 30-minute run with a live gate — 2026-09-25: the gate failed, which is the point.**
> `SOAK GATE FAILED: session transport max 2359.8 ms > 100 ms`, exit 1. The old windowed gate
> would have passed this run — the value it gated on was 17.71 ms — so the hardening paid for
> itself on its first long run: the session-wide max is 2,359.8 ms, against 47 samples above
> 50 ms and 24 above 100 ms. The pre-fix 30-minute session, recomputed per packet, is clean
> (avg 8.77 ms, max 18.00 ms, zero samples above 50 ms, largest gap 338 ms), so this is not
> normal pipeline behaviour and not an artefact of the clock fix.
>
> **Cause not established, and the label matters.** The link is loopback UDP: there is no network
> path that can carry a 2.4 s delay, so "transport incident" is the wrong word. The packets show
> two distinct signatures — receiver-side stalls (the Blender thread not polling, consistent with
> session-recording I/O inside the receive path) and genuine sender silence (host CPU
> scheduling). The main incident spans t=80.4–117.1 s with 23 samples above 100 ms and a 2,359 ms
> peak; two further clusters sit at t=168 s (5 samples, 56–94 ms) and t=1,326–1,339 s (9 samples,
> 51–82 ms, plus one 159 ms). Minutes 2 and 23 apply 740 and 1,743 frames against 1,800
> elsewhere; 1,137 frames are missing over the run, 1,025 of them inside the main incident.
> Repro-or-refute plus a record-on/record-off discrimination are the next runs:
> `odd/tasks/soak-stall-incident-investigation.md`.
>
> **This run also exposed a second check that cannot fail.** `CaptureStats.record_invalid()`
> (`addon/telemetry.py:64`) is never called and `UdpReceiver.invalid_count` is never read by the
> consumer, so `invalid_packets` is structurally always `0`: the gate at `tools/soak_gates.py:41`
> can never fire and the UI line at `addon/ui.py:142` can never render. Every "0 invalid" figure
> in this roadmap's M1 evidence is therefore uninformative, not reassuring.
>
> **The stall reproduces in 2 minutes, and this host currently fails the 100 ms bound even then.**
> An independent 2-minute verification run on an otherwise idle machine hit a ~300 ms in-tick
> stall at t+90 s (`session_max_transport_ms` 328.6, `session_max_gap_ms` 312.0, 9 stale
> discards, `SOAK GATE FAILED` on the pre-existing 100 ms check). The failure was not on any new
> gate. So the 30-minute soak criterion is not merely unmet in one run: this host cannot pass it
> until the stall itself is addressed or the bound is made host-aware, which is now part of the
> same M1 measurement-point decision.
>
> **Loss is now measurable.** The gate gains `session_max_gap_ms` (stall detector, session-wide,
> outside the 120-sample window) and `stale_dropped` / `stale_drop_ratio`, and the previously dead
> `invalid_packets` counter is wired. Verified both ways against preserved evidence: the failed
> 30-minute run derives a 3,191 ms max gap and now **fails**; the clean pre-fix run derives 338 ms
> and **passes**. The two new bounds (500 ms, 1 %) are provisional — 312 ms was observed on
> healthy data — and their calibration is an open task.

## M2 — Expression Fidelity — `Open`
Goal: capture that looks right, not just moves.
- [ ] Neutral-pose calibration pass (per performer)
- [ ] Per-channel amplitude normalization (low/med/max capture UI)
- [ ] Adaptive smoothing (latency-aware, micro-expression preserving)
- [ ] Corrective layer driven by combined control values (pose-space)
- [ ] Perceptual validation against reference recordings

**Exit criteria:** calibrated vs uncalibrated side-by-side perceptually approved; smoothing latency cost within budget.

## M3 — Rig Profiles — `Open`
Goal: beyond ARKit-52 shape keys — the differentiating layer.
- [ ] Profile format + manager (per-rig mapping definitions)
- [ ] ARKit-52 shape key profile (name-based, automatic)
- [ ] Rigify / FaceIt facial rig profile
- [ ] Generic autorig profile via assisted rig probing (canonical expression pose → response learning)
- [ ] Custom controller rig profile

**Exit criteria:** one non-FaceIt, non-ARKit rig animated end-to-end from webcam; probing session ≤ 15 min.

## M4 — Recording, Bake & Export — `Open`
Goal: production output, not just live preview.
- [ ] Record mode: fixed-FPS sampling, batched keyframe insertion
- [ ] Bake to F-curves on target rig
- [ ] FBX export validation (including autorig rigs; AdvanceSkeleton-style pain points)
- [ ] Reproducible session bundles (settings + stream + rig profile)

**Exit criteria:** recorded take → baked → exported FBX loads clean in a second tool (e.g., Maya).

## M5 — Open-Source Preparation — `In progress` (overtaken by an early publication — see note)
Goal: run RealCapture as a public, fully open-source project.
- [x] Repository public — published 2026-09-26 at github.com/AgusLoza2021/RealCapture, ahead of this milestone's other items and of M4 exit; the whole tree is public, including `addon/rigprofile/` and `addon/binding.py` (the planned public/private split did not happen and is no longer planned)
- [x] License declared: GPL-3.0-or-later — `README.md` and `LICENSE`; calling the Blender Python API requires GPL, and the Extensions Platform accepts only GPL-3.0-or-later for add-ons
- [ ] Third-party notice file (Apache-2.0 for MediaPipe, BSD-2 for OpenSeeFace)
- [ ] Blender Extensions packaging: `blender_manifest.toml` + Extensions Platform listing
- [ ] Contribution guide
- [ ] OSC/VMC transport option for VTuber ecosystem interop
- [ ] Original/permissively-licensed demo assets (VALORANT assets excluded)
- [ ] Public docs: install, quickstart, rig-profile guide
- [ ] README/demo media pass

**Exit criteria:** a stranger can install and run; packaging meets the Extensions Platform's requirements.

> **Reconciled 2026-09-26 — the repository was published ahead of this milestone.**
> RealCapture went public today under GPL-3.0-or-later while M5 was still marked
> `Open (blocked until M4 exit)`; that block and the "private side" framing are overtaken by
> the publication decision. Only what is verified is ticked above (repository public, license
> declared); what genuinely remains open is left unchecked: Blender Extensions packaging
> (`blender_manifest.toml`), the third-party notice file, and the contribution guide. Nothing
> else in this roadmap's decisions or recorded evidence is altered by the publication; the
> locked-decisions line above remains the historical record of what was decided at M0.

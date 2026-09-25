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
- [x] Stability soak test: 30+ min live session, no degradation, no crash — 53,415 applied @ 29.98 fps, 0 invalid, 0 failures (`odd/tasks/m1-stabilization.md`)

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

## M5 — Open-Source Preparation — `Open` (blocked until M4 exit)
Goal: release the open side without exposing the private side.
- [ ] Repository split: public addon + private capture/mapping binaries (transport schema is the seam)
- [ ] License decision (MIT vs GPL) + third-party notice file (Apache-2.0, BSD-2)
- [ ] OSC/VMC transport option for VTuber ecosystem interop
- [ ] Original/permissively-licensed demo assets (VALORANT assets excluded)
- [ ] Public docs: install, quickstart, rig-profile guide
- [ ] README/demo media pass

**Exit criteria:** clean-room review: no private methodology in public tree; a stranger can install and run.

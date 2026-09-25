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
- [ ] Git repository initialized, M0 committed
- [ ] Public README stub (positioning + IP note, no methodology)

**Exit criteria:** docs reviewed; repo has M0 commit.

## M1 — Stabilization Harness — `Open`
Goal: trustworthy plumbing before feature work.
- [ ] Capture backend runner as external process (both engines), own venv
- [ ] UDP/JSON transport, latest-frame-wins receiver in `bpy.app.timers` (30–60 Hz)
- [ ] Per-stage latency telemetry (overlay/panel) + session log
- [ ] Epsilon gating + property write path (controller object + native drivers)
- [ ] Session record/replay of packet streams
- [ ] Stability soak test: 30+ min live session, no degradation, no crash

**Exit criteria:** end-to-end latency measured ≤ 60 ms on reference scene; 30-min soak clean; telemetry visible.

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

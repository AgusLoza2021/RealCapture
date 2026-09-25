# Feature: M1 — Stabilization Harness

## Goal
Trustworthy plumbing before feature work: external capture process (both engines),
UDP latest-frame-wins receiver in Blender, per-stage latency telemetry, session
record/replay, and a clean 30-minute soak.

## Locked decisions (from TDD)
- Backends: MediaPipe Face Landmarker (default) + OpenSeeFace (alternative), common interface
- Transport: UDP/JSON, latest-frame-wins; schema in TDD §4.3
- Blender floor 4.2 LTS; Windows-first; Python 3.11 for backend venv
- No Python threads touching bpy; consumer loop via bpy.app.timers at 30–60 Hz
- Epsilon gating; controller-object custom properties + native drivers

## Tasks
- [x] A. Backend core: packet schema module, backend interface, MediaPipe backend (LIVE_STREAM, blendshapes + head pose), run_capture CLI, unit tests for packets — commit eff08f4 (delegation runtime unusable: worktree registration cached pre-git-init; executed inline per declared fallback)
- [x] B. Blender addon: receiver (pure logic + thin bpy glue), consumer timer loop, telemetry panel, scene properties — commit 2cc9d57 (inline fallback, same as A)
- [x] C. OpenSeeFace adapter: spawn facetracker.py, parse its UDP protocol into RealCapture schema — commit 0f9dd87 (inline fallback, same as A)
- [x] D. Session record/replay: JSONL recorder, validating reader, ReplayScheduler with original timing, replay operator sharing the live apply path — commit f59567d (inline fallback, same as A)
- [ ] E. Soak test: 30+ min live session on reference scene, telemetry screenshot + log as evidence
      READY TO RUN (user-side, needs Blender open + live run):
      1. Terminal: python tools/soak_send.py --minutes 30 --hz 30 --port 11111
      2. Blender: addon enabled, controller empty set, Start with Record Session ON (session file default //realcapture_session.jsonl)
      3. After 30 min: Stop, verify applied FPS ~30 stable, transport latency sane, Blender responsive
      4. Evidence: session JSONL + telemetry screenshot; note any drift
      (soak_send verified mechanically: 100 Hz target -> 100.33 Hz actual, 0 send errors)
- [x] F. Docs: addon/README.md (install, quickstart, driver binding, record/replay), backend README (OSF engine + soak), tools/soak_send.py — commit 45ebb74

## Constraints
- Tests must run without mediapipe installed (pure-logic unit tests); heavy deps are import-guarded
- Reviewer protection: each work unit is a separate commit (A, B, C, D); branch m1-stabilization-harness
- No methodology details in code comments beyond what public repo will ship

## Evidence
- (append commit ids per work unit)

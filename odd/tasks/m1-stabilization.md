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
- [ ] D. Session record/replay: capture packet streams to file, replay into addon
- [ ] E. Soak test: 30+ min live session on reference scene, telemetry screenshot + log as evidence
- [ ] F. Docs: backend README quickstart, addon install/test instructions

## Constraints
- Tests must run without mediapipe installed (pure-logic unit tests); heavy deps are import-guarded
- Reviewer protection: each work unit is a separate commit (A, B, C, D); branch m1-stabilization-harness
- No methodology details in code comments beyond what public repo will ship

## Evidence
- (append commit ids per work unit)

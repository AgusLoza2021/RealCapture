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
- [x] E. Soak test: 30-min headless run (Blender 4.5.2 -b, manual 60 Hz tick
      pump + tools/soak_send.py over real UDP). Evidence: soak_output.log,
      soak_output/soak_report.json, soak_output/soak_session.jsonl —
      53,415 applied @ 29.98 fps (target 30), 0 invalid packets, tick p95
      0.21 ms, session lines 53,416 (>= applied), 0 send errors @ 30.00 Hz.
      GUI soak with a live camera remains optional before public release.
- [x] F. Docs: addon/README.md (install, quickstart, driver binding, record/replay), backend README (OSF engine + soak), tools/soak_send.py — commit 45ebb74

## Constraints
- Tests must run without mediapipe installed (pure-logic unit tests); heavy deps are import-guarded
- Reviewer protection: each work unit is a separate commit (A, B, C, D); branch m1-stabilization-harness
- No methodology details in code comments beyond what public repo will ship

## Evidence
- A eff08f4, B 2cc9d57, C 0f9dd87, D f59567d, F 45ebb74 (see task rows)
- E: soak evidence in soak_output/ (headless GUI-equivalent run; live-camera GUI soak optional pre-release); gates passed (>=25 fps avg,
  transport max < 100 ms, 0 invalid, session complete)

> **Correction 2026-09-25.** The "transport max < 100 ms" gate in the row above was
> **vacuous**: `addon/telemetry.py` compared the sender's epoch-ms stamp against the
> receiver's monotonic clock, so `max(0.0, ...)` clamped every sample to exactly `0.0`, and
> the gate at `tools/blender_soak.py:130` tested that constant. The soak result was real;
> its latency claim was not evidence of anything. Fixed the same day — see
> `odd/tasks/milestone-closure-m0-m1.md`. Re-measured over real UDP: avg 9.1 ms / max
> 18.0 ms (transport + consumer apply only).

# Feature: Universal Rig Connector (open-source binding layer)

Open-source part of RealCapture (per IP decision 2026-09): Face Point Drivers,
setup wizard, auto-matching, and JSON rig profiles. The private solver
(calibration, correctives, fidelity) plugs in later via the profile schema.

Research basis: docs/research/rig-mapping-workflow-landscape.md (Rokoko
detection pattern, Expy-Kit bind/unbind, open-mocap empties+constraints).

Branch: rig-connector (off m1-stabilization-harness)

## Work units

- [x] 1. Pure core: canonical channel set (ARKit-52), name standardization
      (side/prefix/suffix/separator handling), alias lists (authored),
      versioned RigProfile JSON schema, auto-match engine with confidence.
      Evidence: commit 3fe637e — addon/rigprofile/ (naming, channels, aliases,
      profile, matcher) + 58 tests; 101/101 passing; demo: mixed catalog
      (Jaw_Open, Eye_Blink_*, Brow_Up_L/R, Mouth_Smile_*, vrc.v_aa) matches
      12/13 controls, one-to-one enforced.
- [x] 2. Blender binding layer: FPD empties (parented to head bone), shape
      keys driven DIRECTLY by the consumer (drivers rejected: Blender 4.x
      does not build depsgraph deps for late-created target props), bones via
      native COPY_LOCATION constraints, one-shot idempotent Unbind.
      bpy glue only in addon modules.
- [x] 3. Setup wizard UI: Scan & Auto-Match -> review table (include toggles +
      confidence) -> Build & Bind -> Load Profile & Bind; registered in the
      Rig Connector panel (ui.py).
- [x] 4. Example preset (addon/presets/example_rigify_style.json) + README
      (Rig Connector guide, face points explained). Rigify/FaceIt/VRM alias
      coverage lives in the alias lists; more presets ship with real rigs.

## Constraints

- Artifacts in this feature are OPEN SOURCE (license decision pending before
  any public release; code stays private until user publishes).
- No copying from LGPL/GPL repos: patterns only, alias lists authored here.
- Packet schema unchanged; FPD movement happens consumer-side from channels.
- Blender 4.2 LTS floor; no threads touching bpy.

## Evidence

- WU1: commit 3fe637e (above).
- WU2+WU3: commit e072a3d (binding layer + wizard + consumer hook, 110/101->110
  tests), dad2d98 (direct-write shape keys after driver invalidation findings,
  blender_smoke_test 19/19 in Blender 4.5.2 headless).
- WU4: commit fcd4633 (docs + example preset).
- End-to-end smoke: build_scene -> register -> scan (9 proposals) -> bind ->
  consumer packet -> rc_shape_* written, shape keys written directly,
  jaw empty moved exactly -0.05, constraint present -> unbind sweeps all.
- 30-min soak (headless, real UDP): 53,415 packets applied @ 29.98 fps,
  0 invalid, tick p95 0.21 ms, session JSONL complete (53,416 lines).
  soak_output/soak_report.json + soak_output.log.

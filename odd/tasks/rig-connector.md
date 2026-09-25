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
- [ ] 2. Blender binding layer: create FPD empties (parented to head), bind
      shape keys via drivers, bind bones via constraints, one-shot Unbind.
      bpy glue only in addon modules.
- [ ] 3. Setup wizard UI: scan -> review table -> bind -> save/load profile.
- [ ] 4. Presets (Rigify/FaceIt/VRM naming) + docs + README for the tool.

## Constraints

- Artifacts in this feature are OPEN SOURCE (license decision pending before
  any public release; code stays private until user publishes).
- No copying from LGPL/GPL repos: patterns only, alias lists authored here.
- Packet schema unchanged; FPD movement happens consumer-side from channels.
- Blender 4.2 LTS floor; no threads touching bpy.

## Evidence

- (filled per work unit)

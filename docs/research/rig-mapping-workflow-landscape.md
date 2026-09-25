# Rig Mapping & Universal-Rig Setup: Workflow Landscape

Research pass: high-star GitHub projects whose workflows inform RealCapture's
M3 (rig profiles) and the "face points as parents" universal-rig binding goal.
Checked 2026-09; stars/licenses via GitHub API at time of writing.

## Repos evaluated

| Repo | Stars | License | Relevance |
|---|---|---|---|
| yeemachine/kalidokit | 5713 | MIT | Canonical expression->rig solver mapping (deprecated; reference standard for semantic channel names) |
| saturday06/VRM-Addon-for-Blender | 1710 | MIT | VRM blendshape proxy: preset-driven canonical expressions |
| Rokoko/rokoko-studio-live-blender | 504 | LGPL-3.0 | The most complete open setup wizard pattern (source-inspected, see below) |
| pKrime/Expy-Kit | 438 | GPL-3.0 (in practice) | Constraint-based binding between rigs with rig presets (Rigify/Mixamo/Unreal/DAZ); clean Bind/Unbind lifecycle |
| lewdineer/Kimodo_Blender_Bridge | 139 | none (unusable as-is) | UX pattern only: fuzzy auto-match bones -> review table -> apply constraints -> bake |
| Larenju-Rai/open-mocap-blender | 121 | MIT | "Retarget to any rig" via empties + COPY_ROTATION/COPY_LOCATION/DAMPED_TRACK constraints; Blender <= 4.0 only |
| Arcomade/BlendCap | 78 | GPL-3.0 | Full performance capture (body+face) from a single video; newer entrant |
| harlynkingm/ARKit-Pose-Recorder-for-Blender | 0 | Apache-2.0 | Inverse direction: pose bones -> bake into 52 ARKit shape keys; reusable JSON presets |

Also reviewed (low stars, informational): csjohnst/blender-mocap (MediaPipe ->
auto Rigify bone mapping), philgatt/Blender-Face-Motion-Capture-AR-Kit,
ysk424/niramekko (iPhone ARKit OSC receiver), tsikerdekis/ARKit-Creator.

## Key pattern: Rokoko's auto-detection (source-inspected)

`core/detection_manager.py` + `core/auto_detect_lists/` implement the exact
"easy setup on any rig" loop:

1. **Name standardization** before matching: lowercase, strip known prefixes
   (`Bip01_`, `ValveBiped_`), separators (`:`, `-`, spaces -> `_`), suffixes
   (`S0`, `_Jnt`).
2. **Alias lists per semantic channel**: `bone_list['hip'] = [...]`,
   52 ARKit shape keys each with an alias list (`shapes.py`).
3. **Priority order**: user's custom aliases > default aliases > exact match.
4. **Review, never blind apply**: every detected mapping lands in a UI table
   the artist can override per channel.
5. **Custom schemes manager**: user-defined mappings are saveable/loadable
   schemes (JSON-backed) — our "rig profile" concept, independently confirmed.

## How this validates the "face points as parents" model

Two complementary binding targets, both natively supported by Blender:

- **Face Point Drivers (FPD)**: a fixed set of canonical empties (brow.L/R,
  eye.L/R, jaw, mouth.corner.L/R, lip.top/bottom, cheek.L/R ...) parented to
  the head, driven by RealCapture each frame. Rig bones/bones-controls become
  *followers* via Copy Location / Copy Rotation / Damped Track constraints —
  the same mechanism open-mocap uses for bodies. The point is the parent;
  the rig link is a native constraint, inspectable and removable by the artist.
- **Channel -> shape key drivers**: ARKit-52 / native channels drive shape
  keys through drivers on the controller properties (already implemented in M1).

Implication for the architecture: the FPD set belongs to the **mapping layer**
(private IP seam), not the transport. The packet schema stays unchanged.

## Proposed M3 setup wizard (informed by these workflows)

1. **Scan**: enumerate the target rig's shape keys and facial bones.
2. **Auto-match**: standardize names (Rokoko-style), match against per-channel
   alias lists; report confidence; user custom lists override.
3. **Review UI**: channel -> detected control table, dropdown overrides,
   unmatched channels highlighted.
4. **Bind**: shape keys get drivers; bones get constraints from FPD empties;
   everything reversible with one Unbind (Expy-Kit pattern).
5. **Profile**: save the full mapping as a JSON rig profile; presets for
   Rigify/FaceIt/VRM/MetaHuman-style rigs ship as examples (VRM addon and
   Expy-Kit both ship presets — artists expect it).

## Licensing notes

- MIT/LGPL/Apache repos above are reference-only for us; no code copying into
  RealCapture (IP policy). Patterns and alias-list *concepts* are not
  copyrightable; literal lists we author ourselves.
- Kimodo Bridge and several smaller repos have no license: patterns only,
  never code.
- Kalidokit's canonical channel naming is MIT-licensed and widely mirrored;
  useful as a compatibility target for our import layer.

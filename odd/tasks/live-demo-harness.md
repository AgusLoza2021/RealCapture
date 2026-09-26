# Feature: Live demo harness — make the rig visible in a Blender window

Status: **in progress** (authorized by the owner: "dale mecha a todas estas", 2026-09-25).

## Why this exists

The owner asked: "would be nice to open Blender, see the live camera and the rig moving — are we
at that height?" A read-only reconnaissance answered **no**, and named three independent gaps.
This feature closes the third one, which is the one that needs no download and no rig asset.

### Gap 1 — the synthetic rig cannot deform
`tools/blender_smoke_test.py:59-61` creates shape keys with `shape_key_add(name=...)` and **never
writes `key_block.data[i].co`**. Every key is identical to Basis, so the 4-vertex quad
(`:56-57`) cannot deform even when `addon/binding.py:62-63` sets `key_block.value`. Nothing
visible moves except the FPD empties, which are 1 cm spheres (`addon/binding.py:23-24`,
`128-150`).

### Gap 2 — the soak stream cannot move anything by construction
`tools/soak_send.py:33` emits `soakShape0..7`. The binding resolves channels by exact ARKit name
(`addon/binding.py:71-73`, `addon/rigprofile/defaults.py:17-47`) and misses every one of them, so
a soak run moves nothing at all. The soak measures transport, not rig motion — consistent with
the standing rule that a successful soak is not proof a rig works.

### Gap 3 — there is no GUI pump
The only packet pumps in the repository are a blocking `while True` loop
(`tools/blender_soak.py:79-93`, documented at `:11` as a background-mode workaround because
"bpy.app.timers do not fire in background mode") and a single synchronous apply
(`tools/blender_smoke_test.py:125`). The addon's own live timer path
(`addon/consumer.py:87` `bpy.app.timers.register(self._tick, ...)`) is never exercised by any
committed harness. Run the soak without `-b` and you get a frozen window for the whole run.

## What this feature delivers

A new `tools/blender_live_demo.py` that opens a real, responsive Blender window in which
geometry visibly deforms, driven through the **addon's own apply path on the addon's own timer**.

1. A crude but genuinely deformable face mesh: real geometry, with per-key vertex offsets so
   each shape key moves what it names.
2. Shape keys named with **real ARKit channel names**, so they bind against
   `addon/rigprofile/channels.py` and the wizard matcher instead of a private vocabulary.
3. The addon registered **by path, without installing it** (`import addon; addon.register()`),
   the route the reconnaissance confirmed works with the existing valid `bl_info`
   (`addon/__init__.py:17-25`).
4. A **non-blocking** drive: the consumer's `bpy.app.timers` tick
   (`addon/consumer.py:87`) plus a second light timer that manufactures ARKit-named packets.
   The GUI stays interactive, unlike `tools/blender_soak.py`.
5. A camera, a light and a material, because the repository creates none — a grep for
   `bpy.data.cameras|bpy.data.lights|camera_add|light_add` across `tools/` and `addon/` returns
   no matches, so nothing in the scene is presentable as-is.
6. Two modes: `--self-drive` (no camera, no downloads, no second process) and the default
   UDP-listen mode that a real backend can feed.
7. A **`--self-test` mode** that runs headlessly, applies a known sweep, asserts that named
   shape-key values changed *and* that the vertex coordinates those keys control actually moved,
   then exits 0 or 1. This is the mode CI and the orchestrator can verify, because a GUI cannot
   be asserted from here.
8. An optional `--render <path>` that writes a PNG of the deformed state, so the result can be
   seen without a human at the keyboard.

## Non-goals

- **Do not modify `tools/blender_smoke_test.py` or `tools/blender_soak.py`.** The soak harness
  is under active measurement work and the smoke test is the reference contract.
- No change to `addon/` source. This is a new tool that consumes the existing apply path; if the
  demo needs an addon change, that is a separate finding, reported not patched.
- No wire or schema change.
- No third-party rig asset, and therefore no committed asset of any kind.
- Not a replacement for a real rig: a demo mesh proves the *path*, never the *character*.
- No claim that this closes the M1 soak failure or the vocabulary defect.
- No commit, push or PR without explicit owner authorization.

## Tasks

| id | Task | State |
|---|---|---|
| T1 | Build the deformable demo mesh with real ARKit key names and real vertex offsets. | done |
| T2 | Register the addon by path and drive it on its own timer, non-blocking. | done |
| T3 | Add `--self-test` (headless assertions) and `--render <png>`. | done |
| T4 | Add camera, light and material so the scene is presentable. | done |
| T5 | Orchestrator verifies: `--self-test` exits 0 headlessly; a render PNG shows deformation. | done — plus an end-to-end run the plan did not anticipate |
| T6 | Document the two commands in the repository docs. | done below |

## Evidence produced

- `--self-test` on Blender 4.5.2 LTS: **exit 0**, `LIVE DEMO SELF-TEST PASSED`, with a per-channel
  table of basis coordinate, evaluated coordinate, delta and controlled vertex index. Mutation
  check: with one key's vertex offsets removed the same command printed
  `FAILED CHANNEL: browOuterUpRight: no vertex moved relative to Basis (max delta 0.000000 <= 0.005)`
  and exited **1**, so the assertion can fail.
- Render PNG: `soak_output/live_demo.png`, 468454 bytes,
  sha256 `e77d3e690de0c143061b9fd72bfee95438aa68c621b21568d6b199e1eb2023a0`.
- **Honest reading of that render:** the frame shows a smooth deformable sheet with a visible
  indentation, not a recognizable face. It proves the deformation, not the character. The mesh is a
  spatial proxy whose vertex offsets are hand-authored by region; it is not facial topology.
- `python -m pytest tests -q` → **173 passed**, no regression.
- **End-to-end run added by the orchestrator after delivery** (the strongest evidence, and it was
  not part of the original plan): the real camera backend was run against camera 0 while Blender
  executed this demo's own `setup_and_bind()` and pumped the consumer manually, the same
  background-mode workaround `tools/blender_soak.py:69` uses. All 8 bound channels received
  non-zero values from live camera inference and the mesh deformed.
  Caveat on the metric: that run's *vertex delta* column is a whole-mesh maximum, identical for
  every channel, so it proves the mesh deforms, not which channel deformed it. Per-channel vertex
  attribution comes from `--self-test`, which reports the specific controlled vertex index.

## Commands

Visible, self-animating, no camera and no downloads:

```
"C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --python tools/blender_live_demo.py -- --self-drive
```

Driven by the real camera (two terminals; the backend needs `backend/.venv` and downloads the
model on first run):

```
backend/.venv/Scripts/python.exe backend/run_capture.py --engine mediapipe --camera 0 --fps 30 --port 11111
"C:/Program Files/Blender Foundation/Blender 4.5/blender.exe" --python tools/blender_live_demo.py
```

Press `0` (or numpad 0) to look through the demo camera. Headless checks:
`-- --self-test` and `-- --render soak_output/live_demo.png`.

## Findings reported instead of patched

1. The Blender startup file injects its own objects (a `Cube` appeared in the first render). The
   demo clears objects when building its scene; `addon/` was not touched.
2. No `addon/` change was needed. `addon/binding.py` writes `key_block.value` correctly; the only
   reason nothing moved before was that no test mesh had vertex offsets in its shape keys.

## Constraints and non-goals inherited from the project

- Blender 4.5 is the target; the addon declares a 4.2 floor (`addon/__init__.py:21`).
- The demo must not require `mediapipe`, `cv2` or any download in `--self-drive` mode.
- Keep it one file so it can be deleted without touching the pipeline.

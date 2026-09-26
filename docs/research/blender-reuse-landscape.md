# Blender reuse landscape — capture, rig mapping, weights, live transport

Surveyed 2026-09-26 on the owner's directive: reuse what people already exposed instead of rebuilding.
Method: GitHub search API plus the sources fetched this session (response ids `muiqlq4xxg70vp`,
`muiqr6ti14afiu`, `muiqrrxed73eqn`). Licenses were read from each repo's own license endpoint, not from
prose, and are quoted as found. Star counts and dates come from search results and were not re-checked
per repository.

## The headline

**Webcam facial capture into Blender is commodity.** At least five independent addons implement the
MediaPipe → ARKit shape keys → Blender path that this project spent its effort on. What is *not*
commodity, and therefore what this project should own, is:

1. a **trustworthy status surface** (what is connected, and is it working),
2. connecting **somebody else's rig**,
3. **correcting the weights** when a channel misbehaves.

That is precisely the owner's plan. The market gap is the tool, not the tracker.

## Capture — our own pipeline, already built by others several times

| repository | what it does | license as read | verdict |
| --- | --- | --- | --- |
| `philgatt/Blender-Face-Motion-Capture-AR-Kit` | MediaPipe + ARKit shape keys, real-time inside Blender | **no license file** (endpoint 404) | ideas only |
| `mozi1924/mediapipe-facecap-for-blender` | MediaPipe facecap addon, 6 releases, active 2025 | **GPL-3.0** | GPL: copyable only if this project goes GPL |
| `ghif/face-mocap-3d` | MediaPipe + OpenCV → ARKit blendshapes (Blender 4.2.3, MediaPipe 0.10.18) | **no license file** | ideas only |
| `Daniel-W-Blender-Python/VIPER-Blender-Facial-Motion-Capture` | MediaPipe Face Landmarker → 3D character, real time | not read | ideas only |
| `cgtinker/BlendArMocap` | markerless MediaPipe tracking inside Blender, transfers to rigs | long GPL-family text returned | GPL: verify the exact variant before relying on it |
| `elijah-atkins/ARKitBlendshapeHelper` | **generates** the ARKit blendshapes on a mesh | **no license file** | the missing piece for bring-your-own-rig: idea yes, code no |

The last row matters: a rig that does not ship the 52 shapes needs them created. The concept is
directly relevant to phase 2; the implementation is not copyable.

## The mapping data we were about to author by hand

**`saturday06/VRM-Addon-for-Blender`** — MIT (the SPDX headers also offer `GPL-3.0-or-later`;
the license endpoint returns the MIT text), ~1.7k stars, 162+ forks, actively maintained,
Blender 2.93 → 5.2. Its source already contains the two tables this project was about to write
from scratch:

- `src/io_scene_vrm/common/human_bone_mapper/human_bone_mapper.py` — imports `biped_mapping`,
  `mixamo_mapping`, `mmd_mapping`, `microsoft_rocketbox_mapping`,
  `cats_blender_plugin_fix_model_mapping`: **humanoid role normalization for the major naming
  conventions, already written**.
- `src/io_scene_vrm/common/shape_key_mapper/arkit_mapping.py` — `ARKIT_SHAPE_KEYS` and
  `VRM1_PRESET_TO_ARKIT_SHAPE_KEY_MAPPING`, alongside `mmd_mapping` and `ready_player_me_*`.
- `src/io_scene_vrm/editor/vrm1/property_group.py` — `initial_automatic_bone_assignment` and
  hierarchy filtering: the **autofill-then-correct** UI pattern, which is the same shape as the
  owner's "let me fix the blink" requirement.

Verdict: **reuse (MIT, with the notice preserved) or depend on it.** This is the single most valuable
find of the survey, and it removes the largest hand-authoring risk in phase 2.

## Live transport — a standard already exists

| item | what it is |
| --- | --- |
| **VMC protocol** (`protocol.vmc.info`) | a publicly documented OSC/UDP spec for streaming live motion into Blender; a de-facto standard in the VTuber ecosystem |
| **`VMC Link`** (extensions.blender.org) | an official Blender extension, actively maintained (0.4.0, Aug 2026). Receives VMC/OSC and applies it to an armature and face mesh: body bones, finger bones, eye movement, shape keys for visemes and expressions, recording, **manual bone mapping**, **autofill bones / autofill blends**, **clear overrides**, configurable refresh rate. Requests network permission to receive UDP. |
| `scaledteam/HEVA_Portal`, `fnoji/Blender-Rigify-Finger-LiveLink`, `VMC4B` (tonimono) | a crowded receiver ecosystem, with users publicly comparing them on accuracy and frame rate |

**This project's packet is private; VMC is a standard with mature receivers.** The strongest
architectural candidate from this survey: **emit VMC as an interop output** rather than replacing the
internal path. Then any VMC-speaking tool can drive a Blender rig from our capture, and our capture
becomes useful outside this project — which is exactly what "good open-source tool" means.

Two unknowns must be confirmed before this is a decision: the spec's own terms, and whether VMC
defines any **receiver-status/back-channel**. The traffic-light design needs a back-channel, and if the
standard already has one it should be used instead of inventing a heartbeat.

## Weights and vertex groups

| repository | what it offers | license as read |
| --- | --- | --- |
| `theRussetPotato/weights_editor` | list + editable table views, add / subtract / scale / set presets | not read |
| `alienware377/VNyan-Weight-Studio` | paint, smooth, rebalance at runtime, then export VRM/VBX | not read |
| `BlenderBoi/Vertex_Group_Utils` | vertex-group utilities for modelling workflows | **GPL-3.0** |
| `kxn4t/vertex-group-merger` | merges groups with **additive or subtractive** weight calculation | **GPL-3.0** |
| `samuelbourland/scaleVertexGroup` | precise scaling of weights on individual vertices | not read |
| `cessen/blender_vg_tools` | managing and manipulating vertex groups and weights | not read |
| `Kroklion/k-blender-tools` | addon framework where **submodules can be enabled individually** | **GPL-3.0** |

Verdict: the operations are **settled and small** (add, subtract, scale, set, normalize), the UI
pattern is settled (**selection + table + preset buttons**), and most implementations are GPL.
**Write our own pure functions — they are a few lines — and take the UI pattern, not the code.** The
`k-blender-tools` modularity framing is worth copying as an idea: independently enableable submodules
is the same shape the owner asked for.

## Licensing consequence — this now blocks work

- **MIT** (`VRM-Addon-for-Blender`) → reusable, notice preserved. Compatible with almost any choice.
- **GPL-3.0** (BlendArMocap, mediapipe-facecap, Vertex_Group_Utils, vertex-group-merger) → copying
  forces this project to GPL as a whole. Legitimate, but only if that is the chosen license.
- **No license at all** (`ARKitBlendshapeHelper`, `philgatt`, `ghif`) → all rights reserved.
  Reading them for ideas is fine; copying their code is not.

`README.md:114` records "None declared yet". So the license decision is no longer a paperwork detail
deferred to M5: it is the **prerequisite for reuse**, and it also has to coexist with the project's
existing runtime dependency on MPFB2 (GPLv3).

### VERIFIED — what the addon's license is actually forced to be

Asked and answered from the publishers themselves, not from blog posts:

> "What about add-ons or my Python scripts? If you share or publish Python scripts **they have to be
> made available licensed as GNU GPL** as well, if they use Blender Python API calls."
> "Can I sell add-ons for Blender? Yes you can, **but only if you provide the add-on and the sources to
> your clients under the GNU GPL license**."
> — Blender FAQ, <https://www.blender.org/support/faq/> (read 2026, section "Using Blender")

> "The Blender Extensions Platform only supports free and open source extensions compliant with
> Blender's license: For add-ons, the required license is **GNU General Public License v3.0 or later**.
> For assets used in add-ons, the required license is **Public Domain (CC0)**."
> — Blender Manual, <https://docs.blender.org/manual/en/latest/advanced/extensions/licenses.html>

Consequences, in order of how much they change the plan:

1. **A published `addon/` must be GPL, and GPL-3.0-or-later if it goes on the Extensions Platform.**
   This is not a preference we get to weigh; it is the condition on which bpy may be called. So the
   earlier worry — "GPL-3.0 code forces the whole project to GPL" — is **moot and now backwards**: this
   project is already committed to a GPL addon by its choice of platform, which makes GPL-3.0 the
   *safest* third-party code to copy, not the most dangerous.
2. **MIT code can be included in a GPLv3 work**, keeping the original notice. That is the whole point of
   MIT's one-way compatibility, and it covers the VRM addon's mapping tables we were about to hand-write.
3. **GPL-2.0-only code cannot be combined with GPLv3 code** (GPL-2.0-or-later can). Worth checking per
   file before copying anything from the older addons; the blanket "GPL" label in the survey above is not
   precise enough to rely on.
4. **CC0 for assets is the platform's requirement**, which the `faceunits01` face-unit pack already meets.
5. **Not forced:** `backend/`, the dashboard, the pure test suites, and any tool that talks to Blender
   over a socket instead of calling the Python API. The rule above is scoped to scripts that *use the
   Blender Python API*, so `tools/blender_*.py` (they run inside Blender and `import bpy`) are GPL,
   while the capture backend that sends UDP to the addon is not. A single license for the whole repo is
   still simpler to explain than a per-directory split, and it is what most addon repositories do.
6. **MPFB2 is a runtime dependency, installed by the user into their own Blender** — depending on GPL
   software does not relicense this project. Vendoring or redistributing MPFB2 would be a different
   question, and nothing here does that.

**Recommendation to the owner:** one `LICENSE` = **GPL-3.0-or-later** for the repository. It satisfies
bpy, it is the only license the Extensions Platform accepts for add-ons, it makes the MIT tables legally
reusable immediately, and it ends the per-file license archaeology. The cost, stated plainly: anyone who
receives the addon may read and redistribute it, so a closed-source commercial addon is off the table.

## What this changes in the plan

1. **Do not hand-author** an ARKit↔semantic table or a humanoid bone map. MIT tables exist.
2. Add **"VMC as an interop output"** as a candidate work unit in `modular-rig-targets.md`.
3. The differentiator is confirmed: **capture is not the product.** The status window,
   bring-your-own-rig, and weight correction are.
4. The **license decision moves earlier**, and it constrains what may be reused.

## Unverified

- Licenses not read: VMC Link, the VMC spec itself, `cessen/blender_vg_tools`, `Daniel-W/…/VIPER`,
  `scaledteam/HEVA_Portal`, `VMC4B`, `weights_editor`, `VNyan-Weight-Studio`, `avatar-stage`.
- Whether the VMC spec provides any receiver-status or back-channel.
- Whether `VMC Link`'s manual bone mapping is scriptable rather than hand-only.
- The exact SPDX variant of each "GPL" repository above (GPL-2.0-only vs -or-later vs -3.0) — the
  distinction decides combinability, and only the license text per repository settles it.
- Whether `VRM-Addon-for-Blender`'s mappers can be consumed as a library without importing the whole
  addon, or whether the tables should be vendored with attribution.

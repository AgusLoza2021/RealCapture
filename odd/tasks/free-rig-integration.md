# Feature: Free-rig integration — drive a real downloaded character

Status: **path A executed 2026-09-25/26 — MPFB2 acquired and a real character driven.** The
shape-key path is proven perfect (**52/52 exact**); the bone path is **defective and visibly tears a
real rig**, which is now T9. T1 and T2 are answered. Nothing third-party has been committed and
nothing may be.

## Why this exists

Every piece of motion evidence in this project today is **synthetic**: `tools/blender_smoke_test.py`
builds a 4-vertex quad with six shape keys and four bones, and that is what all 19 checks and
the soak test exercise (`tools/blender_smoke_test.py:build_scene`). M1 could be closed on that,
but M2 (Expression Fidelity) and M3 (Rig Profiles) cannot be validated without a **real**
character: real bone hierarchy, real shape-key sets, real rest orientations, real rig scale.
The user asked for a free rig from the internet we can actually connect.

## What the connector requires (verified from code, 2026-09-25)

Mapped read-only with file:line evidence. This is the acceptance criteria for any candidate.

| Requirement | Detail | Reference |
|---|---|---|
| Channel vocabulary | `ARKIT_CHANNELS`, exactly **52**, ARKit-52 names (`jawOpen`, `mouthSmileLeft`, `eyeBlinkLeft`, …); asserted `== 52` | `addon/rigprofile/channels.py:16,41` |
| Shape keys | **Implemented.** The consumer writes `key_block.value` directly each tick, no drivers; profile `shapekey_bindings` resolve to key blocks | `addon/binding.py:62,177` |
| Bones | **Implemented, but as pose-bone `copy_location`.** The wizard only ever emits `copy_location`; `copy_rotation` and `damped_track` exist in the schema and are reachable only by hand-editing the profile JSON | `addon/binding.py:217,241`; `addon/rigprofile/profile.py:19` |
| Helper empties on a rig | **Not supported as a target.** The connector creates its *own* face-point empties, parented to the head bone, and makes rig bones follow them. It cannot drive a rig's pre-existing helper objects | `addon/binding.py:119,144` |
| Head bone | Required, or the bind raises `No head bone found`. Auto-detection only accepts a bone whose lowercased name **starts with** `head`, so `mixamorig:Head` or `DEF-head` must be set explicitly. **Materialized as a real defect on MPFB2 — see T9: on a FACS muscle-bone rig the bone named `head` is not at the head at all.** | `addon/binding.py:123,169` |
| Minimum bind gate | **None.** A bind with zero matches succeeds and does nothing — a silent no-op, so a "successful" bind proves nothing. **Confirmed and worse than documented: the bind on MPFB2 reported full success (`52 shape keys, 3 bones, 11 point transforms`) while visibly tearing the character.** | `addon/rigprofile/matcher.py`; T9 below |
| Gains and offsets | Absolute meters, no rig-size normalization; the default face-point offsets are documented rough guesses | `addon/rigprofile/defaults.py`; `addon/binding.py:155` |
| Rig scale | A centimetre-scale or oversized rig will move the wrong amounts | same |

**The channel vocabulary is no longer unknown (T1 answered).** Measured live on 2026-09-25:
MediaPipe emits 52 categories — the 51 ARKit names plus `_neutral` — so the shape-key path matches
by exact name for essentially every channel, and `tongueOut` can never arrive. What remains true is
the *defence* gap: the lookup is exact string equality with no normalization layer and no minimum
bind gate, so a rig whose shape keys are named anything else binds "successfully" and moves
nothing. **The rig's own key names are therefore the first thing to verify**, which is what the T3
plan below does before anything is built on top of it.

## Candidates (licenses and versions checked 2026-09-25)

| # | Candidate | License | Blender | Facial data | Fit |
|---|---|---|---|---|---|
| **A** | **MPFB2** — MakeHuman Plugin For Blender, from the official extensions platform | Code GPLv3; **assets CC0** | **4.2+** (we run 4.5) | `faceunits01` asset pack provides **ARKit-compatible face shapes**; Export Copy can bake **visemes + ARKit face units** into a copy | **Best.** CC0, generated locally, full-body rig with a head bone, shape keys named for ARKit → drives the implemented shape-key path end to end |
| **B** | **Google VALID avatars → VRM 1.0** (`TLTMedia/valid-vrm-avatars`, 210 rigged avatars) + the official **VRM Add-on for Blender** | **CC BY 4.0** (attribution required) | import via the official VRM extension | Full **ARKit 52** blendshapes on the head mesh | **Strong.** A genuine downloaded rig with exact ARKit-52 names, clean license, real variety |
| **C** | **Blender Studio characters** — Snow, Rain, Gabby, Einar | **CC BY 4.0** | Snow/Rain/Gabby: 3.6 LTS ✓. **Storm requires Blender 5.0 — excluded** | Production facial rig: layered controls, shape-key correctives, ribbons, lattice | **Useful second target.** Real production rig, but control-driven with non-ARKit naming, so it maps few channels and rotation-only controls will not follow `copy_location` |
| — | `JRicardoSan/Blender-ARKit-compatible-heads` | Repo `LICENSE` is MIT, **but its README states the FBX comes from Dragonboots' MetaHuman head, which is "intended for study purposes only", and says that still applies** | FBX, no version constraint | One head with ARKit blendshapes | **Not recommended.** Technically the fastest match (single FBX, ARKit names) but the asset's own terms are study-only, and it ships no armature, so a bind would raise `No head bone found` without a helper armature |

## Recommendation

**Path A, then B.** A is CC0 with no attribution burden, is generated in Blender rather than
downloaded, and lands directly on the implemented shape-key path. B is the actual "free rig from
the internet" and adds real-world variety at the cost of an attribution line. C is the right
target only after the connector can drive rotation-based controls, which is a separate feature.

**No rig asset may be committed to this repository.** Assets live outside the repo (or under a
gitignored `assets/`), and their provenance and license line is recorded in the task doc and in
the M3 documentation. A third-party CC-BY asset must never be vendored silently.

## Tasks

| id | Task | Depends on |
|---|---|---|
| T1 | **Verify the vocabulary seam. ANSWERED 2026-09-25 — see `odd/tasks/producer-vocabulary-contract.md`.** The seam is exact string equality at `addon/binding.py:55-71` with **no normalization layer anywhere** (the layer `docs/realcapture-tdd.md:153` claims as a mitigation does not exist); OpenSeeFace resolves **0 of its 16** producer names; **16 of the 52** channels have no default point transform; and MediaPipe's real name set **cannot be read from the repository** (the model is downloaded at runtime and `backend/models/` does not exist). One real run with a webcam produces the name set for free, because `addon/consumer.py:129` exposes every producer name as `rc_shape_<name>`. T2 below still blocks T3–T8. | none |
| T2 | **Path A chosen by the owner (2026-09-25): MPFB2.** License line for the M3 docs: MPFB2 code is **GPLv3**, its asset packs (including `faceunits01`) are **CC0**, and a character a user generates with it carries no attribution obligation. No vendoring: the asset is generated locally and lives outside the repository. | done |
| T3 | **DONE 2026-09-25.** MPFB2 **2.0.8** installed into an isolated Blender config (newer versions exist only on the extensions platform, whose direct download returned an HTML challenge page), plus the **`faceunits01`** pack from `files.makehumancommunity.org/functional/faceunits01.zip` (CC0). A default human with the standard rig and the 52 face-unit targets was generated to a `.blend` outside the repo. **The head-mesh vocabulary is ARKit-52 exactly: 52 present in both, 0 only in MPFB, 0 only in ARKit.** The pack ships one `.target` per ARKit channel, so this is not "compatible", it is the same vocabulary. The scan matched **52/52 shape-key proposals at exact confidence**. (Beside them the mesh carries MPFB-internal non-ARKit keys — `Basis` and 8 `$md-…` macro keys, 61 total — which the scan correctly ignores.) | done |
| T4 | Write a real-rig harness. `tools/blender_smoke_test.py` hard-codes its synthetic names and calls `build_scene()` unconditionally, so opening a real `.blend` would still create and test the synthetic rig (and collide into `.001` names). Add a script that opens a given `.blend`/`.vrm`, assigns `rig_armature` / `rig_face_mesh` / `rig_head_bone`, runs scan → bind, feeds a packet, and inspects the result. Do not modify the committed synthetic smoke test. | T3 |
| T5 | **PARTIAL — see below.** The shape-key path is proven on a real character; the bone path tears it. "The bind succeeded" is still not evidence, exactly as this doc predicted. | T4 |
| T6 | Record the real-rig rig profile and the face-point placement/gain values that worked, as a preset under `addon/presets/`, so path A or B is reproducible without re-tuning. | T5 |
| T7 | Automate the real-rig check the way the synthetic one is automated, so M2/M3 have a regression gate on a real character. | T5 |
| T8 | Feed the findings back: record the rig-scale and rotation-control gaps as their own decisions (rig-size normalization, and whether to enable `copy_rotation`), rather than silently widening this doc. | T5 |
| T9 | **NEW DEFECT, found 2026-09-25 on MPFB2 and it is a connector defect, not an MPFB2 bug.** Head-bone auto-detection picks a bone by name prefix only and never checks that the bone is anywhere near the head. On the MPFB2 rig the bone named `head` sits at **z = 0.697 m** (confirmed twice: `bone.head_local.z` and the posed world position both read 0.697) on a **1.667 m** figure, while the actual skull is held by FACS muscle bones at **z = 1.56–1.65 m** (`special05.R`, `oculi01.R`, `temporalis01.R`). The face-point empties are parented to that head bone and the 3 bound bones follow them with `copy_location`, so the mesh is torn apart. Needs a geometric sanity check on the head bone plus the missing minimum bind gate. **CLOSED 2026-09-26 (commit `171da07`); see the closure section below.** | T5 |

## Path A execution plan (T3)

Order matters: the vocabulary check comes second, because everything after it is wasted if the key
names do not match and the mismatch is silently absorbed by the missing bind gate.

1. **Install MPFB2** into the Blender 4.5 installation (Blender extension or addon zip). The addon
   itself is not vendored; it is an install on this host, and the install command is recorded.
2. **Create a default human, add its face, and apply the `faceunits01` asset pack.** Then **enumerate
   the actual shape-key names on the head mesh and diff them against `ARKIT_CHANNELS`**
   (`addon/rigprofile/channels.py:16`). This is the load-bearing step.
3. **Branch on that diff, honestly.** If the names are ARKit-52, proceed. If they are MakeHuman-style
   names (`mouth_open`, `brow_up`, …), then the exact-name lookup at `addon/binding.py:55-71` will
   bind nothing, and the shape-key path needs a mapping — which is a **new owner decision** (the same
   one as T1 of `producer-vocabulary-contract.md`), not a silent private workaround inside a rig
   profile.
4. **Check the head bone.** A bone whose lowercased name starts with `head` is required or the bind
   raises `No head bone found` (`addon/binding.py:123,169`). If MPFB2's rig names it differently, set
   `rig_head_bone` explicitly in the profile rather than renaming a third-party rig.
5. **Harvest to a `.blend` outside the repository**, because an MPFB2 install on this host is not
   reproducible in another environment. Use whatever MPFB2 export path bakes the face units into
   real shape keys rather than leaving them as generator parameters.
6. Only then T4 (harness) and T5 (a **named** key moving).

Explicitly out of scope for this pass: rig-size normalization, and rotation-based control support.
Both are T8.

## Non-goals

- No changes to the packet schema or to `addon/schema.py`.
- No vendoring of any third-party asset into the repository.
- No new dependency for the addon: the VRM add-on is optional and only for path B.
- No connector redesign. Rotation-driven control support and rig-size normalization are
  separate features and are recorded as T8, not implemented here.
- No claim that a successful scan/bind means the rig works.

## What the real rig proved (2026-09-25/26)

`tools/blender_mpfb_demo.py` opens the generated character, assigns `rig_armature` /
`rig_face_mesh` / `rig_head_bone`, runs the real `scan_rig` → `bind_rig`, and pumps one packet
through the real `CaptureConsumer._apply` path.

**What works, proven with numbers.** All 52 ARKit channels are bound as `gain: 1.0`, exact
name-to-same-name, in the profile the operator wrote. Fed `jawOpen = 0.9`, the head mesh's `jawOpen`
key reads back **0.900** and a controlled vertex moves **0.0349** Blender units. The rendered result
is a **recognizable human face** — eyes, nose, mouth, ears — and the expression reads clearly:
`jawOpen 0.85` + both smiles `0.95` + blinks `0.55` produces a clean open-mouthed smile. The
isolated measurement, applying the same values straight to the shape keys with no bind at all, is
**0.0321 m** of maximum vertex displacement, which is exactly the scale a real face should move.
**Path A is a perfect fit for the implemented shape-key path.**

**What is broken, and how it was isolated.** With the bind in place the character is **visibly torn**
— long stretched spikes radiating from the face — and it is torn **at rest, with every shape value at
zero**, i.e. before a single packet arrives. The three-way isolation:

| Condition | Armature modifier | Our bind | Max vertex move, all keys 0 | Result |
|---|---|---|---|---|
| Fresh open, keys set directly | on | none | **0.0000 m** | clean |
| Fresh open, keys set directly | off | none | 0.0000 m | clean |
| Real `bind_rig` then apply | on | **active** | spikes | **torn** |

So the deformation is caused by the bind's own bone and point-transform work, not by MPFB2, not by
the shape keys, and not by the armature at rest. The profile the operator wrote names the culprit:
`head_bone: head`, 11 `points`, and 3 `bone_bindings` targeting `eye.L` / `eye.R` with
`copy_location`. The empties those bones copy are parented to a head bone that is ~0.95 m below the
the face, so the eye bones snap to the wrong place and drag the mesh with them — while the operator
still reports **"Bound: 52 shape keys, 3 bones, 11 point transforms"**.

This is the same failure family as the three vacuous metrics, the dead invalid counter, and the
unpinned dependency: **a check that reports success over a broken artifact.**

**The fix direction (T9).** Bind by geometry, not by name: validate that the detected head bone is in
the upper part of the mesh, and when it is not, either refuse the bone/point path outright or bind
**shape keys only** — which for MPFB2 is already a complete, correct 52/52 mapping. A muscle-bone
rig should not be driven by `copy_location` at all.

### T9 CLOSED, 2026-09-26 (commit `171da07`)

Implemented exactly as above, plus the minimum bind gate the connector never had.

- `addon/rigprofile/headbone.py` (new, pure, no `bpy`): `choose_head_bone()` requires the lowercased
  name to start with `head` **and** the bone to sit at or above the mesh midpoint plus a 5 %-of-height
  margin; the highest qualifying bone wins, otherwise `None`. `exceeds_rest_gate()` is the ceiling
  (`REST_GATE_THRESHOLD = 0.25 m`). `is_gate_measurable()` is the order-independent mesh-selection
  rule.
- `addon/binding.py`: with no qualifying head bone the point/bone path is skipped and the bind falls
  back to **shape keys only**; after the bone path, `_measure_rest_displacement()` evaluates the
  depsgraph with every shape key at 0 and compares against Basis; on failure
  `_remove_point_bone_bindings()` removes the `RC_follow_*` constraints and the FPD empties, restores
  the pre-bind pose, and the residual is **measured, not assumed**.
- `addon/wizard.py`: a rejected point/bone path is reported as a WARNING naming the measured
  displacement, the rejected bone, its height and the fix — never as full success.
- `tests/test_headbone_gate.py`: 32 pure tests. Suite 178 → **210 passed**.
- **The 0.25 m threshold is deliberately loose.** The empties are placed by `_default_offset`, a rough
  guess, so an artist-repositioned rig legitimately moves bones by ~0.1–0.15 m; a 1 cm gate would
  false-positive. 0.25 m is "clearly broken" territory and catches the 0.8211 m tear. The measured
  number is always recorded and reported even when the gate passes.

Measured on the real character (`<RC_MPFB_ROOT>/tmp/character.blend`, the isolated MPFB2 environment),
with every shape key at 0 and the baseline taken from a fresh open with no bind at all:

| | before T9 | after T9 |
| --- | --- | --- |
| worst vertex displacement vs Basis | **0.8211 m** | **0.0000 m** |
| FPD empties left behind | 11 | 0 |
| `RC_follow_*` constraints left behind | 3 | 0 |
| operator message | "Bound: 52 shape keys, 3 bones, 11 point transforms" | WARNING naming the rejection and the fix |
| `jawOpen = 0.9` still moves the mesh | — | 0.0349 m by shape key |

Visually confirmed by re-rendering the same two poses through the addon path: the neck and skull are
intact and the face is a clean, recognizable smiling human. The torn renders are kept alongside them
as `soak_output/mpfb_face_*_TORN_before_t9.png` (renders are gitignored).

**Two lessons worth keeping.**

1. **The first version of the gate was dead by construction and its own author reported it as
   working.** It selected meshes by a marker property (`rc_driven_shapekeys`) that is written *after*
   the gate runs, so the candidate list was empty, the measurement was `None` and the gate never
   fired. The independent verification caught it: the mesh was still torn 0.8211 m with the "fixed"
   code loaded. `is_gate_measurable()` plus tests now pin the selection rule, and the fix is only
   accepted because the number moved.
2. **Measure a baseline before calling a delta damage.** The first post-fix reading was 0.0621 m,
   which looked like leftover damage from an incomplete revert. It was the file's own saved non-zero
   shape values: the same 0.0621 m appears on a fresh open with no bind at all, and drops to
   0.0000 m once the values are zeroed. Two candidate root causes were chased (a dead counter, then
   leftover pose) before the baseline measurement settled it. The pose-restore in
   `_remove_point_bone_bindings` was kept as correct undo semantics, but it is **not** what fixed the
   number, and it is documented as not load-bearing here: `copy_location` drives the evaluated
   matrix without writing `pose_bone.location`.

## Evidence

- Connector requirements mapping, 2026-09-25 (read-only, file:line; see the table above).
- Licenses and Blender-version floors checked 2026-09-25:
  `github.com/makehumancommunity/mpfb2` (LICENSE.md; 4.2+),
  `static.makehumancommunity.org/mpfb/docs/exporting/export_copy.html`,
  MPFB 2.0.16 release notes (`faceunits01`, ARKit-compatible face shapes),
  `github.com/TLTMedia/valid-vrm-avatars` (CC BY 4.0),
  `github.com/google/valid-avatar-library` (210 rigged avatars),
  `studio.blender.org/characters/snow/v3/` (CC-BY, layered face controls, 3.6 LTS),
  `studio.blender.org/characters/storm/v1/` (requires Blender 5.0 — excluded),
  `github.com/JRicardoSan/Blender-ARKit-compatible-heads` (MIT file, study-only asset).
- No rig has been downloaded or opened yet. **SUPERSEDED 2026-09-25/26:** MPFB2 2.0.8 and the CC0
  `faceunits01` pack were installed into an isolated config and a character was generated outside the
  repository. The vocabulary verdict is 52/52 exact, the shape-key path is proven on a real face, and
  the bone path is a new defect (T9). Renders: `soak_output/mpfb_raw_smile.png` (clean, shape keys
  only, no bind — **a real human face with a clear expression**) and `soak_output/mpfb_face_neutral.png`
  / `mpfb_face_smile.png` (same values through the bind — **torn, at rest**). `soak_output/` is
  gitignored, so these images are local evidence only. The `.blend`
  (`<RC_MPFB_ROOT>/tmp/character.blend`, 18,009,107 bytes) lives outside the repository, as required.
- Harness verification by the orchestrator, not taken on report: `tools/blender_mpfb_demo.py` exits
  **0** on the real character and exits **1** under mutation (`--value 0` → `no vertex moved relative
  to Basis on 'jawOpen'`), so its assertion can fail. Guard paths exit 3 (no `.blend`) and 4 (no MPFB).
  178 tests pass.

## T10 — control coverage sweep + expression poses (opened 2026-09-26)

Requested by the owner: "armate diferentes poses, probá blink, smile, angry, a ver si funcionan
todos los ctrls."

Two questions to answer with numbers, not with renders:

1. **Coverage.** Do ALL 52 channels actually move the mesh on the real MPFB2 character? A render that
   looks plausible is not evidence; the measurement is max vertex displacement against the rest pose,
   per channel. Any channel measuring ~0 is investigated individually before being called broken.
   Known upstream truth to keep separate from this test: `tongueOut` is never emitted by MediaPipe
   1.0.1 (51/52 exact), and 16 of the 52 channels have no point transform in
   `addon/rigprofile/defaults.py` — the real character binds shape-keys-only (post-T9), so the
   question here is whether the SHAPE KEYS cover all 52.
2. **Expressions.** Renders of named poses (blink, smile, angry, and a couple more) produced through
   the real bind path, sent to the owner so he can judge them himself.

Work: `tools/blender_mpfb_live.py` gains a `--sweep` mode (all 52 in ONE Blender session, because one
process per channel would take half an hour) and a `--pose <name>` render mode. Reference for the
proven camera/render setup: a scratch render script kept outside the repository.

### T10 RESULT, 2026-09-26 — 52/52 measured, 5 poses rendered

**Coverage, measured (not rendered).** `tools/blender_mpfb_live.py --sweep` drives every channel in
`ARKIT_CHANNELS` one at a time in ONE Blender session and records the maximum evaluated-mesh vertex
displacement against a forced all-zero rest. **52/52 OK, zero DEAD**, exit 0. The parent re-ran it and
got numbers identical to the worker's run:

| | channel | max disp (m) |
| --- | --- | --- |
| strongest | `jawOpen` | 0.038738 |
| | `mouthClose` | 0.035928 |
| | `tongueOut` | 0.027467 |
| | `mouthSmileLeft` | 0.018682 |
| weakest | `eyeLookUpLeft/Right` | 0.002912 |
| | `eyeWide/eyeSquint*` | 0.003917–0.003947 |

Two things this settles and one it separates:

- The **shape keys** cover all 52 channels on the real character (the earlier "16 of 52 have no point
  transform" note is about the *point-transform* table in `addon/rigprofile/defaults.py`; the real
  character binds shape-keys-only, so that table is not what drives it).
- `tongueOut` **does** move this mesh (27 mm). Its gap is the **producer**: MediaPipe 1.0.1 never
  emits it (51/52 exact). A shape-key gap and a producer gap are different defects; do not merge them.

**Expressions.** `--pose blink|wink|smile|angry|surprise|all` renders through the real bind path to
`soak_output/mpfb_pose_<name>.png` (the existing `mpfb_face_*.png` are never overwritten). The parent
looked at all five: blink is both eyes shut, wink is one eye shut and it is the correct eye, smile
lifts the corners and the cheeks, surprise drops the jaw with wide eyes.

**Angry was wrong, and the bug was in the pose definition.** v1 included `browInnerUp: 0.3` — the
*sadness* cue, the inner-brow-raise "puppy eyes" shape — which fights anger, and the render showed it:
the face read as mildly annoyed. v2 removes it and adds squint 0.85, sneer 0.85, upper-lip raise 0.6,
lip press 0.6 and frown 1.0. Honest ceiling: this clay render has **no visible eyebrow hair**, so brow
motion moves skin that is hard to see; the brow channels measure 6.95 mm, the perception limit is the
asset, not the control.

**Lesson.** A pose that looks plausible is not evidence that a control works, and a named expression
can sabotage itself through a channel that means the opposite in FACS. Measure every channel; eyeball
every render; do not let either one stand in for the other.

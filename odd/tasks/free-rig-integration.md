# Feature: Free-rig integration — drive a real downloaded character

Status: **proposed — waiting on one owner pick (path A/B/C below).** Read-only exploration done
2026-09-25; nothing downloaded, nothing committed.

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
| Head bone | Required, or the bind raises `No head bone found`. Auto-detection only accepts a bone whose lowercased name **starts with** `head`, so `mixamorig:Head` or `DEF-head` must be set explicitly | `addon/binding.py:123,169` |
| Minimum bind gate | **None.** A bind with zero matches succeeds and does nothing — a silent no-op, so a "successful" bind proves nothing | `addon/rigprofile/matcher.py` |
| Gains and offsets | Absolute meters, no rig-size normalization; the default face-point offsets are documented rough guesses | `addon/rigprofile/defaults.py`; `addon/binding.py:155` |
| Rig scale | A centimetre-scale or oversized rig will move the wrong amounts | same |

**The one unknown that decides everything:** MediaPipe's blendshape `category_name` values are
forwarded verbatim and looked up by their exact ARKit channel name, and **no test asserts the two
vocabularies agree**. If they differ by even one name, that channel silently never moves. This must
be measured before any rig work (T1).

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
| T2 | Decide the path (A, B, or C) and record the license line. | owner |
| T3 | Acquire the rig outside the repo, with provenance recorded: path A installs MPFB2 from the extensions platform and exports a copy with ARKit face units; path B downloads one VALID VRM and imports it with the VRM add-on. | T2 |
| T4 | Write a real-rig harness. `tools/blender_smoke_test.py` hard-codes its synthetic names and calls `build_scene()` unconditionally, so opening a real `.blend` would still create and test the synthetic rig (and collide into `.001` names). Add a script that opens a given `.blend`/`.vrm`, assigns `rig_armature` / `rig_face_mesh` / `rig_head_bone`, runs scan → bind, feeds a packet, and inspects the result. Do not modify the committed synthetic smoke test. | T3 |
| T5 | Prove motion: drive a packet and show a **named** shape key moving on the real mesh, with its asserted value. "The bind succeeded" is not evidence, because there is no minimum bind gate. | T4 |
| T6 | Record the real-rig rig profile and the face-point placement/gain values that worked, as a preset under `addon/presets/`, so path A or B is reproducible without re-tuning. | T5 |
| T7 | Automate the real-rig check the way the synthetic one is automated, so M2/M3 have a regression gate on a real character. | T5 |
| T8 | Feed the findings back: record the rig-scale and rotation-control gaps as their own decisions (rig-size normalization, and whether to enable `copy_rotation`), rather than silently widening this doc. | T5 |

## Non-goals

- No changes to the packet schema or to `addon/schema.py`.
- No vendoring of any third-party asset into the repository.
- No new dependency for the addon: the VRM add-on is optional and only for path B.
- No connector redesign. Rotation-driven control support and rig-size normalization are
  separate features and are recorded as T8, not implemented here.
- No claim that a successful scan/bind means the rig works.

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
- No rig has been downloaded or opened yet.

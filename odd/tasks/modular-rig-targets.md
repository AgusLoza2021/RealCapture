# Feature: Modular rig targets (bring your own rig, fix the weights)

Phase 2 of the owner's onboarding plan, and the one that makes the tool *a tool* rather than one
character. Owner's requirements, in intent:

- configure **several different models**;
- **import an external rig and read its hierarchy** to connect our face points to that rig;
- configure **skin-weight zones**;
- be **modular**;
- net goal: connect a custom rig, connect our camera, and **modify the weights** so that when
  something does not work (his example: blink), the user can fix the rig and have it all match.

Phase 1 (the window) comes first so the user can see what is connected while doing this:
`control-room-window.md`.

## The hard truth this feature has to face first

**T9 proved that the bone/point path tears a real rig at rest** (0.8211 m of damage on an untouched
mesh, driven by a bone named `head` that sat at chest height). The fix deliberately made the real
character bind **shape-keys-only** and refuse the bone path, and added a geometric head-bone gate
(`addon/rigprofile/headbone.py`) plus a rest-displacement gate that can fail.

Phase 2 asks for the bone path back: an external rig, mapped point by point, with editable weights.
That is legitimate and it is the right direction for "any rig", but it means **phase 2 partially
reverses the T9 decision**. The correct way back is not to un-refuse the old guess; it is:

- the bone path returns only **behind validation** (the head-bone and rest gates are the precedent),
- the mapping is **discovered and then user-correctable**, never hardcoded,
- a bind that cannot be validated **says so and refuses**, instead of reporting success over a
  damaged mesh — the exact failure class this project already paid for once.

## Reuse before rebuild

The owner's directive: reuse what people already exposed rather than rebuild. Survey result,
with licenses read from each repository: `docs/research/blender-reuse-landscape.md`. Two findings
land directly in this feature:

- **Do not hand-author the mapping tables.** `saturday06/VRM-Addon-for-Blender` (MIT, ~1.7k stars,
  active) already carries humanoid bone mappers for the major naming conventions (biped, mixamo, mmd,
  rocketbox) and an `ARKIT_SHAPE_KEYS` / preset↔ARKit shape-key map, plus an autofill-then-correct
  bone assignment UI. Reuse with the notice preserved, or depend on it.
- **Emit VMC as an interop output.** VMC protocol (OSC/UDP) is a documented standard with mature
  Blender receivers, including an official extension (`VMC Link`, active in 2026) that already does
  manual bone mapping, autofill bones/blends and override clearing. Speaking it makes this capture
  useful to the wider ecosystem without asking anyone to adopt a private format. Confirm first
  whether VMC defines a receiver-status/back-channel, because the traffic-light design needs one.

## Research sync — what the field already does (the owner asked for internet data)

| Finding | Source | What it means for us |
| --- | --- | --- |
| Rig-role normalization is a solved, named problem: one rig calls the head bone `mixamorigHead`, another `J_Bip_C_Head`, a third just numbers bones. Existing tools normalize rigs onto **canonical humanoid roles** and detect across Mixamo / Character Creator / hand-rigged exports. | `rana-jatin/avatar-stage` (GitHub) | Reading the hierarchy and mapping it to **roles** is the right architecture, and there is precedent. Do not invent a private vocabulary. |
| Blender's own Rigify face rig **requires a naming convention** to find the eyelids: two child skin chains tagged `.T` and `.B` for top/bottom. | Blender 5.0 Manual, `face.skin_eye` (docs.blender.org) | The industry pattern is **convention discovery first**. A rig that declares itself is far more reliable than geometry guessing — which is exactly the mistake T9 punished. |
| Professional facial rigging weight-paints the eyelids by **subtracting from a master eye bone** and assigning the difference to individual deform bones; **auto-blink needs a separate guide/target mesh** blended between upper and lower lid. | Blender Studio, *Advanced Facial Rigging* (eyelids weight painting, weight painting, eyes, auto blink) | "Blink does not work" is usually **a weight/zone problem plus a missing target shape**, not a missing channel. The user's instinct — let me edit the weights — is correct. |
| Existing weight editors converge on the same UI: **list view + editable table**, with preset **add / subtract / scale / set** buttons, per selected components, then export. | `theRussetPotato/weights_editor`; `alienware377/VNyan-Weight-Studio` (GitHub) | The editing surface is known; we do not need to invent it. Scope is per-zone ops on selected vertices, not a freehand brush. |
| Blender already ships an automatic starting point: **weight from bones**, with control over how bones influence the generated maps. | Avalab *Avastar* "Generic Face Maps" (deliveries.avalab.org) | Do not hand-roll an automatic weighting algorithm. Generate a starting point, then let the user correct it. |
| Semantic blendshape mapping across meshes is an established pattern (same semantic shape, different mesh → sync by role). | `bdunderscore/modular-avatar`, "Blendshape Sync" | The channel → target binding belongs in a **data mapping keyed by semantic role**, which is what makes this modular. |
| Neural rigging exists and is not the answer here: transfer facial animation to arbitrary topology with no manual rigging. | `dafei-qin/NFR_pytorch`; Blanco et al., *Facial Retargeting with Automatic Range of Motion Alignment* (2017) | Named so it is a decision, not an omission: **not now**. It adds a training/runtime dependency and cannot be inspected or corrected by the user, which is the opposite of this feature's goal. |

Sources were retrieved this session; full results are stored under response id `muiqlq4xxg70vp`.

## Architecture (draft — modular is the requirement, so the seams come first)

Pure where possible, `bpy` only at the edges, so every unit is testable without Blender:

- **`TargetAdapter`** — the contract a driveable target implements: enumerate what it can be driven
  with (shape keys / bones / hybrid), apply a channel value, report what it actually did, and
  validate itself. Candidate implementations: shape-key adapter (today's proven path), bone
  adapter (behind gates), hybrid.
- **`RigProfile` (discovered)** — roles read from the imported rig's hierarchy: face mesh, head bone
  candidate *with the gate's verdict*, eye/mouth/jaw chains found by convention, deform bones, and
  what could not be identified. Discovery is **reported, never silently guessed**.
- **`ChannelMap`** — channel → target role, keyed by semantic role, user-editable, serialisable, so
  a custom rig's mapping is a file the user can keep, diff and share.
- **`WeightZone`** — a named region (vertex group / landmark-derived selection) with the four
  operations the field uses (add, subtract, scale, set) plus normalize, expressed as pure functions
  over weight data, applied through the adapter.
- **The existing gates stay in charge.** `headbone.py` and the rest-displacement gate are the
  reason the bone path is allowed back at all; nothing in this feature may bypass them.

## Work units

Reconciled after phase 1 landed (`850a362`, `a4bc300`). Phase 1 shipped the window, the camera
endpoints, the Blender back-channel, the truth table and the launchers. Phase 2 starts from the pure
core outward, because those units are testable without Blender and only R2/R4/R5b/R6 need `bpy`.

Ordering rule: **nothing touches the proven shape-key path** (52/52, T10) until the pure units around
it exist, so a live session is never disturbed by a refactor of the bind that works.

- [x] R0. Reuse survey + license read (`docs/research/blender-reuse-landscape.md`, `5824ec0`).
- [x] R5a. **Weight-zone operations, pure** (`addon/rigprofile/weights.py`): the four ops the field
  converges on (add, subtract, scale, set) over a named zone, plus per-vertex normalize and an
  influence limit. Spec frozen below; evidence in "R5a - evidence".
- [x] R3. `ChannelMap` as data — **dropped as a phantom unit**; see "R3 - dropped" below. The profile
  already is the channel map.
- [ ] R8. **Report unresolved bindings instead of silently dropping them**: `addon/binding.py:405-412`
  (missing shape key) and `:439` (missing pose bone) `continue` past a binding that does not resolve,
  and the user-facing report (`addon/wizard.py:130-155`) never mentions it. A hand-edited override
  that does not resolve disappears with no message at all: the same defect family as a false green,
  and the only in-Blender override today is exactly that hand edit. **Touches the live path, so it
  waits until no live session is running.**
- [ ] R9. Remove or actually use `context.scene["realcapture_bound_profile"]` (`addon/wizard.py:238`):
  it is written and never read anywhere in the repo, so it is dead state that reads like a feature.
- [ ] R2. Rig import + hierarchy read into a discovered `RigProfile`, role discovery by convention,
  honest "unidentified" list. Needs `bpy` and one real external rig (open question 1).
- [ ] R4. Bone adapter behind the gates, with a refusal path that fails loudly instead of damaging a
  mesh. Partially reverses T9, so it stays last among the adapter units.
- [ ] R1. `TargetAdapter` contract + the shape-key adapter refactored behind it, with the 52/52 sweep
  as the regression proof. Deliberately after R4, so the contract is written against two
  implementations instead of guessed from one.
- [ ] R5b. Blender-side application of a zone edit through the adapter (needs R1 + R5a).
- [ ] R6. The mapping/weight editing surface (table UI, per the field's precedent), wired into the
  phase-1 window (open question 4: browser or Blender panel).
- [ ] R7. Docs: "bring your own rig" walkthrough, plus the T9 lesson stated as a rule.

### R5a — the frozen contract (parent-owned, not the writer's)

`addon/rigprofile/weights.py`: pure, never imports `bpy`, tested on the system Python.

- `WeightZone(name, vertices)`, frozen dataclass: rejects an empty name, an empty selection, a
  negative index and a duplicate index.
- `apply_zone_edit(weights, zone, op, value) -> dict[int, float]`: `op` in `add` | `subtract` |
  `scale` | `set`, result clamped to `[0, 1]`, vertices inside the zone and absent from `weights`
  enter at `0.0`, vertices outside the zone are copied through **clamped as well** (a caller cannot
  smuggle an out-of-range weight past an edit), the input mapping is never
  mutated, and an unknown op, a non-finite value or a non-finite input weight raises
  `WeightZoneError` instead of succeeding quietly.
- `normalize_vertex(weights_by_group) -> dict[str, float]`: one vertex across its groups, sums to
  `1.0`; an all-zero vertex stays all-zero rather than dividing by zero; an empty mapping returns an
  empty mapping.
- `limit_influences(weights_by_group, max_influences=4, *, normalize=False)`: keeps the largest
  influences with a deterministic tie-break, `max_influences < 1` raises.
- `changed_vertices(before, after) -> tuple[int, ...]`: honest reporting for the UI, so the edit
  surface can say what it actually changed instead of asserting success.

The refusal rules are the point of this unit and belong in the tests: an empty selection and an
unknown operation must fail loudly. This project already paid once for a check that reported success
over nothing (the vacuous rest gate, and the `all-zero` bind that read as damage-free).

### R3 - dropped (parent decision, with evidence)

A read-only recon asked whether R3 would duplicate something that already exists. It would.
`RigProfile` (`addon/rigprofile/profile.py:110-118`) already stores all three mappings — channel to
shape key (`ShapeKeyBinding.channel` -> `.target`, `:60-63`), channel to FPD point role
(`PointTransform.channel` -> `.role`, `:31-36`) and point role to bone (`BoneBinding.point` ->
`.target`, `:80-86`) — the derived starting point already exists (`matcher.py:37-57` into
`wizard.py:66-74`), the user override already exists (include/exclude at `ui.py:184` plus a hand edit
of the JSON), and the document already round-trips (`profile.py:120-174`, proven by
`tests/test_rigprofile_profile.py:21-46`). No consumer anywhere resolves a binding by semantic role:
binding resolves by exact shape-key name and exact pose-bone name. A second role-keyed map would have
no reader, which is the duplicated-structure defect this document itself warns about.

What the recon found instead, now recorded as R8 and R9, are real defects rather than a missing class.
The leftover evidence it also produced, worth keeping:

- The review table's target cell is **read-only** (`addon/ui.py:184-187`), so the only in-Blender
  override is include/exclude; a genuine retarget means editing the profile JSON by hand, which the
  code's own prose already assumes (`addon/rigprofile/defaults.py:3-6`). That is R6's job.
- The matcher can only propose `ARKIT_CHANNELS` (`matcher.py:39-41`) and `build_profile` drops anything
  outside the catalog (`build.py:37`), which is R2's discovery problem.
- `rx..tz` pose channels (`addon/schema.py:23`, written as `rc_pose_<key>`) have **no profile
  representation at all**: the runtime only ever reads `packet.shapes` (`binding.py:91`), so driving a
  head bone from head pose is expressible nowhere. Whether a profile may do that is an open question,
  not a defect.
- `addon/rigprofile/profile.py` is the ONE place a channel string is a free, unvalidated string
  (`:60`), while the packet schema accepts arbitrary shape names (`addon/schema.py:105-108`). That is
  deliberate (the OpenSeeFace translation table is R2's problem) and is not a bug.

### Operational constraint discovered while a live session runs

`camera-to-rig.cmd` runs `tools/blender_mpfb_live.py`, and that harness imports the addon **from disk**:
`from addon.ui import _get_consumer` (`:238`), `from addon.wizard import _skip_detail` (`:247`) and
`from addon.rigprofile.channels import ARKIT_CHANNELS` (`:496`). Editing any of those files while a
session is live can therefore break a run the owner is performing at that moment, and a failure he
sees during his own test is indistinguishable from a broken tool. **Rule: while a live session is
running, only new files that nothing imports yet may be written.** Pure units are unaffected (R5a is a
new module no one imports); R8, R2, R4, R6 and anything in `addon/binding.py`, `addon/wizard.py`,
`addon/ui.py` or the existing `addon/rigprofile/` modules wait for a quiet session.

### R5a - evidence

Delivered by a delegated writer, then verified independently by the parent, because a writer's
"done" is not proof.

- `python -m pytest tests/test_rigprofile_weights.py -q` -> **52 passed**; the canonical suite command
  is `python -m pytest tests -q` (the hygiene gate collects `tests/` only, so a bare `pytest -q` at
  the repo root also picks up `tools/blender_smoke_test.py` and dies on `ImportError: bpy`).
- `python -m pytest tests -q` -> **449 passed, 1 warning** after the README count was corrected
  (397 -> 449, the README pin is the parent's surface, not the writer's).
- The module imports only `math`, `dataclasses` and `typing`; `bpy` appears in its docstring prose and
  is never imported. Checked by reading the actual import lines, not by trusting the report.
- **Mutation proof (writer)**: the unknown-op refusal replaced by `pass` -> the refusal test fails
  with `DID NOT RAISE`. **Mutation proof (parent, independent)**: the empty-selection refusal removed
  -> 2 tests fail (`test_rejects_empty_selection` and `test_from_dict_bypasses_no_rule`), which also
  proves `from_dict` revalidates through the constructor instead of trusting its input.
- **Two defects found in parent review and fixed here**: (1) `apply_zone_edit` tested zone membership
  with `vertex in zone.vertices` inside the loop over every weight, which is O(vertices x zone) on a
  real mesh (tens of thousands of vertices); it now builds a `set` once. (2) This document said
  outside-zone vertices "pass through unchanged" while the code clamps them; the code is right (a
  caller must not smuggle an out-of-range weight past an edit) and the document was corrected.
- **Not covered yet**: nothing calls this module. R5b (Blender-side application through the adapter)
  and R6 (the editing surface) are the consumers; until one of them lands, these rules are proven on
  synthetic mappings only, never against a real mesh.
- **Work unit**: committed as `a44eac3` on branch `phase2/weight-zones`.

## Non-goals

- Neural/ML retargeting.
- Supporting every format at once. Pick one first (see below).
- Editing weights as a freehand brush.
- Rewriting the existing ARKit path, which is measured working at 52/52.

## Open questions

1. **Which rig format is first?** Candidates: VRM (license-clean, ARKit-shaped ecosystem), Mixamo/
   generic FBX (common, bone-rich), Rigify (Blender-native, convention-driven). Recommendation:
   pick whichever the owner actually has a rig for, and make the second one prove the seam is real.
2. **How does the user pick a zone?** Landmark-derived region, existing vertex group, or a manual
   vertex selection? The field's editors assume selection + table.
3. **Are weight edits written back to the .blend, or held as an override layer?** Override layer is
   safer and reversible; writing back is what users eventually want.
4. Does the mapping edit surface live in the browser window (phase 1) or in Blender's own panel
   (`addon/ui.py` already has a Rig Connector panel)? The browser is where the user is already
   looking; Blender is where the mesh is.

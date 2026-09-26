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

Not started. Sketch only; this section is expected to change once phase 1 lands.

- [ ] R1. `TargetAdapter` contract + the shape-key adapter refactored behind it, with the existing
  52/52 sweep as the regression proof.
- [ ] R2. Rig import + hierarchy reading into `RigProfile`, role discovery by convention, and an
  honest "unidentified" list.
- [ ] R3. `ChannelMap` as data: derived starting point, user overrides, round-trip serialisation.
- [ ] R4. Bone adapter behind the gates, with a **refusal** path that fails loudly instead of
  damaging a mesh.
- [ ] R5. `WeightZone` ops (pure, unit-tested on synthetic weights) + Blender-side application.
- [ ] R6. The mapping/weight editing surface (table UI, per the field's precedent), wired into the
  phase-1 window.
- [ ] R7. Docs: "bring your own rig" walkthrough, plus the **T9 lesson stated as a rule** — a new
  rig must be validated before it is trusted.

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

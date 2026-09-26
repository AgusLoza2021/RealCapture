# Feature: Producer vocabulary contract — the missing normalization layer

Status: **open defect, reported 2026-09-25 from a read-only reconnaissance.** No code written.
Needs one owner decision (T1) and one real capture (T2) before it can be closed.

## The defect in one sentence

RealCapture maps producer blendshape names to its internal channel vocabulary by **exact string
equality**, and there is **no normalization layer** anywhere between the backend and the rig — so
any backend or model version whose names differ by one character binds successfully and silently
drives nothing.

## Evidence

### The seam is exact equality, in one place
`addon/binding.py:55` `values = packet.shapes`, then `:58` `values.get(entry["channel"])` for the
mesh shape keys and `:71` `values.get(tr["channel"])` for the FPD point transforms, each followed
by a silent `continue` when the lookup returns `None` (`:59-60`, `:72-73`). No case folding, no
separator normalization, no counter, no log. This is the only place where a producer name is ever
compared against the target vocabulary.

Nothing upstream normalizes either: `backend/backends/mediapipe_backend.py:171-173` forwards
`category.category_name` **verbatim** as the packet key, with only a truthiness filter.
`addon/rigprofile/aliases.py` is **not** a translation table — it maps channel bases and point
roles to rig-control aliases, i.e. it serves the *rig* side, and the only module importing it is
`addon/rigprofile/matcher.py`.

### OpenSeeFace is structurally dead: 0 of 16 names resolve
`backend/backends/openseeface_protocol.py:42-57` defines `OSF_FEATURE_NAMES`, and
`backend/backends/openseeface_backend.py:38-42` adds two synthetic keys, giving a complete,
in-repo producer vocabulary of 16 names:

```
eye_l, eye_r, eyebrow_steepness_l, eyebrow_updown_l, eyebrow_quirk_l,
eyebrow_steepness_r, eyebrow_updown_r, eyebrow_quirk_r,
mouth_corner_updown_l, mouth_corner_inout_l,
mouth_corner_updown_r, mouth_corner_inout_r,
mouth_open, mouth_wide, eyeOpennessRight, eyeOpennessLeft
```

**Not one of the 16 equals any of the 52 `ARKIT_CHANNELS`.** Every OpenSeeFace packet is accepted
by the wire schema (`backend/common/packets.py:115-117` only requires non-empty string keys),
decoded, applied to nothing, and counted as a successful apply. The backend's own hand-off note
(`openseeface_backend.py:8-11`) says the mapping layer is responsible for converting
them — and that layer does not exist.

### 16 ARKit channels have no path at all
`addon/rigprofile/defaults.py:15-46` defines point transforms for only 36 of the 52 channels once
side-expanded. These 16 have no default transform, so with a default profile they can only move a
mesh shape key whose name is exactly the ARKit name and which the wizard happened to include:

```
jawForward, mouthClose, mouthDimpleLeft, mouthDimpleRight, mouthLeft,
mouthPressLeft, mouthPressRight, mouthPucker, mouthRight, mouthRollLower,
mouthRollUpper, mouthShrugLower, mouthShrugUpper, noseSneerLeft,
noseSneerRight, tongueOut
```

### The documented mitigation does not exist
`docs/realcapture-tdd.md:153` lists the risk "ARKit-52 semantic drift between backends" with the
mitigation "Channel normalization layer + per-backend unit tests". Neither exists. Prose
elsewhere asserts the vocabularies match without enforcing it: `backend/README.md:69`,
`docs/realcapture-tdd.md:60`, `addon/README.md:31`.

### No test can go red
Nothing under `tests/` imports `addon/binding.py`, `addon/consumer.py`, `addon/wizard.py`, or
`backend/backends/mediapipe_backend.py`. `tests/test_rigprofile_channels.py:6-9` checks only that
the list is 52 long, unique, and side-splittable. `tests/test_rigprofile_matcher.py:15-20` looks
like a contract test but its names are rig shape-key names the test supplies itself, so it would
still pass if MediaPipe renamed a blendshape to `mouthSmile_L`. `tests/test_packets.py:19` uses
three arbitrary strings as payload. The synthetic Blender smoke test hard-codes its own names
(`tools/blender_smoke_test.py:59-60`) and can never disagree with `channels.py`.

## What is still unknown, and why it cannot be read off the code

**The real MediaPipe `category_name` set is not in the repository.** It is compiled into
`face_landmarker.task`, which is downloaded at runtime
(`backend/backends/mediapipe_backend.py:26-30, 84-92`); `backend/models/` does not exist. The
dependency is an open lower bound (`backend/requirements.txt:1` → `mediapipe>=0.10.9`) and no
model version or hash is recorded anywhere, so the emitted name set can change with no diff in
this repository. No sample packet dump, session file, or captured channel list exists either. A
single in-repo claim that MediaPipe also emits `_neutral` comes from `odd/tasks/free-rig-integration.md`
and has no evidence artifact behind it.

**This is cheap to close, because the addon already exposes the producer vocabulary:**
`addon/consumer.py:129` writes every incoming shape name verbatim as the custom property
`rc_shape_<name>`. One real run of the backend with a webcam therefore produces the complete
emitted name set, with no new instrumented code.

## Why this matters beyond one rig

It is the same failure shape as the three vacuous metrics already found in this project: a check
that cannot fail. A wizard scan, a bind, a profile validation, and a soak all report success while
the character does not move.

## Tasks

| id | Task | Depends on |
|---|---|---|
| T1 | **Owner decision: build the normalization layer, or declare OpenSeeFace unsupported.** Options: (a) add a producer→channel normalization step at the seam in `addon/binding.py` with per-backend tables and unit tests; (b) drop the OpenSeeFace path and delete its dead code; (c) keep both backends but surface every unmapped name in the telemetry panel and fail the bind when nothing resolved. | none |
| T2 | **Capture the real MediaPipe vocabulary once** (a short real run; `rc_shape_*` keys from the telemetry panel or a session file) and record it as a checked-in fixture with the observed mediapipe version and model URL. | none |
| T3 | **Pin the contract with a test.** Two independent tests, the second requiring no unknowns and therefore doable first: (i) a pure-pytest test over a stubbed `bpy` calling `addon.binding.FacePointRig.apply` with an exact name and with a near-miss variant, asserting the near-miss does not move; (ii) a fixture-based test asserting `emitted − ARKIT_CHANNELS` equals exactly the known benign extras and `ARKIT_CHANNELS − emitted` is empty. | T2 |
| T4 | **Add a bind-time minimum.** Report how many channels resolved on bind and fail or warn when zero did, since a zero-match bind currently succeeds and does nothing. | T1 |
| T5 | **Close the 16-channel gap** in `addon/rigprofile/defaults.py`, or document explicitly that those channels are shape-key-only. | T1 |

## Non-goals

- **No wire or schema change.** `addon/schema.py` and `backend/common/packets.py` stay
  byte-identical; the fix is receiver-side and addon-side.
- No new dependencies and no changes to the synthetic smoke test.
- Not a claim about any specific rig asset.
- No commit, push, or PR without explicit owner authorization.

## Evidence

- Reconnaissance, 2026-09-25, read-only, no file modified: all `file:line` references above were
  read directly from disk. The OpenSeeFace 0/16 result and the 16-channel gap are derivations from
  those literal strings, not from an executed run — both are verifiable by inspection.
- Not executed by that reconnaissance (no shell available to it): anything requiring Python.

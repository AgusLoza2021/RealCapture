# Feature: Producer vocabulary contract — the missing normalization layer

Status: **open defect, narrowed 2026-09-25.** T1 (owner decision) still open. The load-bearing
unknown — the real emitted vocabulary — is now **ANSWERED with a live capture**, and the answer is
much narrower than feared: **MediaPipe matches 51 of the 52 channels exactly.** What remains
broken is OpenSeeFace (0 of 16), the removed `BaseOptions` re-export, and the 16 channels with no
default point transform.

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
mesh shape key whose name is exactly the ARKit name and which the wizard happened to include.
15 of them **are** emitted by MediaPipe, so the gap bites point-transform rigs:

```
jawForward, mouthClose, mouthDimpleLeft, mouthDimpleRight, mouthLeft,
mouthPressLeft, mouthPressRight, mouthPucker, mouthRight, mouthRollLower,
mouthRollUpper, mouthShrugLower, mouthShrugUpper, noseSneerLeft,
noseSneerRight, tongueOut
```

`tongueOut` is the one member of this set that MediaPipe never emits at all, so it is doubly
unreachable — no transform and no producer.

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

## The real emitted vocabulary — ANSWERED 2026-09-25 by live capture

Captured on this host from camera 0 through the real backend, with `mediapipe 1.0.1` and the
model downloaded from the URL recorded at `backend/backends/mediapipe_backend.py:23-27`:

```
emitted shape keys: 52
not in ARKIT_CHANNELS (1):  _neutral
in ARKIT_CHANNELS, never emitted (1):  tongueOut
exact matches: 51 of 52
```

The full emitted set is the 51 ARKit names plus `_neutral`. Two consequences that correct earlier
assumptions in this repository:

- **The vocabulary risk for MediaPipe is small.** The prose in `backend/README.md:69`,
  `docs/realcapture-tdd.md:60` and `addon/README.md:31` asserting that the vocabularies match is
  **substantially correct for MediaPipe**, and an earlier summary in this session that treated the
  seam as broadly broken overstated it. What is broken is OpenSeeFace and the missing
  normalization *defence*, not MediaPipe's names.
- **`_neutral` is real and confirmed** (the claim had previously existed in
  `odd/tasks/free-rig-integration.md` with no evidence artifact): MediaPipe always emits it as an
  extra category, so any consumer that treats the emitted set as exactly ARKit-52 sees one extra
  name. `tongueOut` can never arrive from this engine, so the 16-channel gap below matters only for
  rigs that need point transforms.

The capture also proves the addon's own exposure route works as predicted:
`addon/consumer.py:129` writes every incoming shape name verbatim as the `rc_shape_<name>` custom
property, so a capture needs no new instrumented code.

### C4 cross-reference (2026-09-27 Start-proof run)

The C4 installed-extension Start proof stored 52 raw produced shape-key names, which decompose as
51 ARKit catalog names plus the extra `_neutral` — exactly the vocabulary recorded above. This
independent run **confirms rather than supersedes** the capture: `tongueOut` remains absent from
the producer vocabulary, and the honest producer claim is `live 51/52`. An earlier C4 summary that
reported "52/52 live producer channels" was a raw-count vs catalog-size conflation and has been
retracted; the harness (`tools/blender_start_proof.py`, report schema `/2`) now computes coverage
from channel NAMES (`coverage_truth`) and enforces, with named constants: exact catalog identity
by SHA-256 digest over the sorted configured names (`EXPECTED_ARKIT_CATALOG_SHA256`), a configured
count of exactly 52, sentinel membership (`tongueOut` required; producer-only `_neutral`
forbidden in configuration), a minimum of 51 live catalog matches, and zero-match fail-closed
behavior. Rig bindings, rig targets, the dashboard heartbeat's 52 bound channels, and C3's
synthetic 52/52 target sweep are separate facts and are not producer-vocabulary evidence.

### Why the capture was blocked for a day, and what it exposed

The risk this document recorded as theoretical — "the emitted name set can change with no diff in
this repository" — **materialized before the capture could run**. `backend/requirements.txt:1` was
`mediapipe>=0.10.9`, an open lower bound, so pip installed **1.0.1**, where
`mediapipe.tasks.python.vision` no longer re-exports `BaseOptions`. The capture loop died
immediately at the old `backend/backends/mediapipe_backend.py:101`:

```
AttributeError: module 'mediapipe.tasks.python.vision' has no attribute 'BaseOptions'
```

Fixed by resolving the symbol **by capability rather than by version** — a pure
`resolve_base_options(module)` with an ordered candidate list and an actionable error naming the
version and every location tried — plus an upper bound in `backend/requirements.txt`, plus pure
stub tests in `tests/test_mediapipe_compat.py` that need mediapipe **not** installed and therefore
can never be skipped away. This is the concrete cost of the unpinned inference dependency this
document predicted.

## Why this matters beyond one rig

It is the same failure shape as the three vacuous metrics already found in this project: a check
that cannot fail — and, as of 2026-09-25, the same shape as a dependency that can change the
emitted vocabulary with no diff. A wizard scan, a bind, a profile validation, and a soak all report
success while the character does not move.

## Tasks

| id | Task | Depends on |
|---|---|---|
| T1 | **Owner decision: build the normalization layer, or declare OpenSeeFace unsupported.** Options: (a) add a producer→channel normalization step at the seam in `addon/binding.py` with per-backend tables and unit tests; (b) drop the OpenSeeFace path and delete its dead code; (c) keep both backends but surface every unmapped name in the telemetry panel and fail the bind when nothing resolved. | none |
| T2 | **Capture the real MediaPipe vocabulary once. DONE 2026-09-25** — 52 emitted, 51 exact ARKit matches, `_neutral` extra, `tongueOut` never emitted. See the capture section above. The fixture still needs to be checked in by T3. | done |
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
- **Live capture, 2026-09-25** (executed, not derived): UDP listener on `127.0.0.1:11111` plus
  `backend/.venv/Scripts/python.exe backend/run_capture.py --engine mediapipe --camera 0 --fps 30
  --port 11111`. Result: 430 packets in 20.5 s, 0 send errors, 52 emitted shape keys. The complete
  name list and the diff against `ARKIT_CHANNELS` are in the capture section above. Negative
  control: the same listener ran for 15 s with nothing sending and correctly reported 0 packets.
- **End-to-end, 2026-09-25** (executed): the live camera drove a bound Blender mesh through the
  real consumer apply path. All 8 bound ARKit channels received non-zero values from camera
  inference and the mesh deformed. This closes the "does a real producer drive a real rig"
  question for the shape-key path; it does not prove any third-party rig works.
- The model artifact itself (`backend/models/face_landmarker.task`) is a downloaded file and is
  gitignored, not committed.

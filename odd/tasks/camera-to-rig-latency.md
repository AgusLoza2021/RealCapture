# Feature: camera-to-rig acquisition latency

Status: in progress
Branch: `feat/camera-to-rig-latency`
Owner decision: frame acquisition is the official start of camera-to-rig latency.
Canonical runner: `python -m pytest tests -q`
Runtime rule: camera and Blender runs are exclusive and sequential.

## Goal

Measure the segment the product actually names: from a successful camera frame acquisition through MediaPipe, UDP transport, Blender consumption, and effective rig application.

The existing `packet.t` remains the post-inference transport timestamp. A new acquisition timestamp travels in the already-supported optional `packet.extra` object, so the system can report both metrics without changing packet schema v1:

- transport-to-apply latency: existing `applied_epoch_ms - packet.t`;
- camera-to-rig latency: new `applied_epoch_ms - packet.extra["acq_t_ms"]`.

## Truth contract

- Acquisition time is sampled immediately after a successful `cap.read()`.
- The asynchronous MediaPipe callback must preserve the timestamp belonging to its exact input frame.
- Missing, malformed, non-finite, future, or otherwise unusable acquisition stamps never become `0 ms`; the metric is explicitly unavailable or invalid.
- Synthetic and replay packets without an acquisition stamp remain valid packets, but cannot claim camera-to-rig latency.
- The existing transport metric keeps its meaning and remains independently visible.
- No result from a short live run closes the failed 30-minute M1 soak.

## Tasks

| id | Work unit | Status | Allowed edit surfaces | Evidence |
|---|---|---|---|---|
| T1 | Stamp each successful camera acquisition and preserve the exact frame stamp through the async MediaPipe callback into `Packet.extra.acq_t_ms`. Add dependency-free tests for exact correlation, no-face behavior, callback reordering, and bounded pending state. | done | `backend/backends/mediapipe_backend.py`; `tests/test_mediapipe_capture_stamp.py` | focused 35 passed; independent verifier PASS; commit recorded below |
| T2 | Add fail-closed camera-to-rig telemetry in Blender: measured sample count, rolling average/max, session max, invalid-stamp count, reset behavior, and truthful UI states. Keep transport telemetry unchanged. | done | `addon/telemetry.py`; `addon/ui.py`; `tests/test_telemetry.py` | 32 telemetry tests + 75 adjacent tests passed; independent verifier PASS; commit recorded below |
| T3 | Extend the installed-Start proof to record and validate camera-to-rig latency as a distinct measured field, update the public test count and milestone/roadmap wording, then run focused, canonical, and one exclusive live proof. | blocked — pending live face presence (not done) | `tools/blender_start_proof.py`; `tests/test_blender_start_proof.py`; `README.md`; `docs/roadmap.md`; `odd/tasks/milestone-closure-m0-m1.md`; `odd/tasks/producer-vocabulary-contract.md`; this file | harness done 2026-09-28; exclusive live attempt failed closed on no face — see T3 evidence below |

## Delivery strategy

The owner selected a five-PR stack on 2026-09-28 because the complete candidate is 1,185
changed lines and exceeds the 400-line review budget. Each PR targets its immediate predecessor
until that predecessor lands; the next PR must then be retargeted to `main` before merge.
Existing commits remain unchanged.

| Position | Branch | Commits | Review budget | Outcome |
|---|---|---|---:|---|
| 1 | `feat/camera-latency-01-acquisition` | `738b0b0` | 343 | Bounded acquisition-stamp correlation. |
| 2 | `feat/camera-latency-02-telemetry-core` | `7c96cc3` | 250 | Fail-closed Blender aggregates. |
| 3 | `feat/camera-latency-03-ui-evidence` | `2f4f1a9`, `4fd0b05` | 193 | Truthful UI state and T2 evidence. |
| 4 | `test/camera-latency-04-proof-harness` | `e5ec555` | 325 | Installed-Start schema `/3` proof harness. |
| 5 | `feat/camera-to-rig-latency` | `5bacd85` plus this delivery record | below 400 | Pending-evidence record; remains draft until a face-visible live run satisfies criterion 6. |

Repository policy note: this repository has no YAML Issue Forms, approved-issue label, PR
template, `type:*` labels, or CI workflows. The stack therefore follows the established direct
verified-integration path rather than fabricating issue linkage or policy labels.

## Acceptance criteria

1. Every emitted MediaPipe packet produced from a captured frame includes an integer epoch-ms `extra.acq_t_ms` correlated to that exact async result.
2. Pending acquisition correlation is bounded and does not leak if MediaPipe drops callbacks.
3. Blender records camera-to-rig latency only from a valid acquisition stamp and never converts missing/invalid data into a healthy-looking zero.
4. UI and proof output distinguish measured camera-to-rig latency from transport-only latency and from unavailable/invalid states.
5. Focused tests and `python -m pytest tests -q` pass.
6. A real installed-extension run observes at least one valid camera-to-rig sample and reports the measured window honestly. Its result does not close M1 stability.

## Non-goals

- No packet schema version change and no edits to the mirrored packet schema modules.
- No new dependency.
- No producer vocabulary normalization or invented `tongueOut` data.
- No change to MPFB2 binding, weight application, or the gated bone path.
- No recalibration of the 30-minute soak gates in this feature.
- No claim of display-photon or externally observed motion latency.

## Work-unit evidence

### T1 — correlate camera acquisition stamps

- TDD RED: the new stamp suite failed on the missing production submission seam (`AttributeError: MediaPipeBackend has no attribute _submit_frame`).
- GREEN: `python -m pytest tests/test_mediapipe_capture_stamp.py tests/test_mediapipe_compat.py tests/test_packets.py tests/test_schema_sync.py -v` -> 35 passed.
- Independent verification: PASS. Exact callback-key correlation, out-of-order delivery, deterministic bounded eviction, no-fabrication behavior, epoch-clock choice, schema-v1 preservation, and import isolation were checked. The production seam and epoch choice have discriminating tests.
- Runtime harness: N/A for T1 because camera/Blender execution is reserved for the exclusive T3 proof.
- Rollback boundary: remove `tests/test_mediapipe_capture_stamp.py` and revert the acquisition-correlation additions in `backend/backends/mediapipe_backend.py`; no other behavior depends on T1 before T2/T3 land.
- Commit: `738b0b06ff044487597da51f57843f14abdb5d30` (`feat(capture): stamp camera acquisition time`).

### T2 — measure latency fail-closed in Blender

- TDD RED: focused telemetry tests exposed missing camera-latency fields/states; the first verifier then rejected null/missing conflation, absent missing-count telemetry, and duplicate chronology coverage.
- GREEN: `python -m pytest tests/test_telemetry.py -q` -> 32 passed; adjacent plugin/cockpit/stamp/packet/schema set -> 75 passed.
- Independent verification: PASS after correction. Missing keys, present-invalid values, rolling and session aggregates, reset, mixed states, distinct error state/icon mapping, and independently discriminating send/apply chronology bounds were checked. Existing transport/FPS/gap semantics and schema v1 remained unchanged.
- Runtime harness: N/A for T2 because the panel/data integration is exercised in the exclusive T3 installed-Start proof.
- Rollback boundary: revert the camera-latency fields/state helper in `addon/telemetry.py`, the additive panel line in `addon/ui.py`, and the T2 tests in `tests/test_telemetry.py`; T1 packet stamping remains independently valid.
- Commits after the authorized review-size split: `7c96cc33464d660cd80c60914fca5ee18f638c3f` (`feat(blender): record camera to rig latency`) and `2f4f1a940d58a6098188d6ced4ed206d9c3ef5a3` (`feat(blender): show truthful camera latency state`). Both slices are below 400 authored changed lines.

### T3 — Start-proof harness landed; live proof blocked on face presence

**Status: not done.** The harness and every pre-live gate are complete; the exclusive live
attempt ran once on 2026-09-28 and failed closed because no face was in view. It has not been
retried, by explicit owner decision.

**Pre-live gates, all observed 2026-09-28:**

- Canonical suite: `python -m pytest tests -q` → **707 passed**, 1 pre-existing third-party
  warning. Self-test passed.
- Extension validator/build: **exit 0**; artifact `dist/realcapture-0.1.0.zip`, 66,824 bytes,
  SHA-256 `b96616fec55329deccbcab5f21772522bc5dd47c059a5282400480dbc20d3dc1`.
- Install verification: the installed `telemetry.py`, `ui.py`, and `__init__.py` hashes matched
  the staged build. Pre-install backup preserved at the run's temporary folder
  (`%TEMP%/realcapture-extension-backup-20260928-101833/`).
- Harness commit: `e5ec555d81b0c031533897ef5c38116158ca7734`; the Start-proof report schema is
  now `/3`.

**Exclusive live attempt** (evidence folder `%TEMP%/rc-latency-proof-20260928-101902/`):

- The disposable `.blend` SHA matched its source; Blender exited **1**.
- The camera opened and the dashboard camera light went **green**, but **no face was detected**:
  zero packets, zero applied packets, zero camera samples. The packets and Blender lights
  stayed red.
- The `/3` verdict **failed closed** rather than reporting a fabricated 0 ms — the intended
  behaviour under acceptance criterion 3, but it means no camera-to-rig sample was observed and
  acceptance criterion 6 remains unmet.
- Cleanup succeeded: the capture/backend stop operators finished, extension state was cleared,
  the backend PID was gone, and UDP 11111 and TCP 8765 were bindable again.

**Owner decision (2026-09-28):** do not retry now; live evidence stays pending.

**Exact next action:** re-run the same exclusive installed-Start proof with a face present in
view, then record the `/3` verdict here. T3 stays blocked until that run observes at least one
valid camera-to-rig sample. This attempt does not close M1 stability.

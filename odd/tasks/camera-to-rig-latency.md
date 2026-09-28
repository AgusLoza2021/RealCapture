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
| T2 | Add fail-closed camera-to-rig telemetry in Blender: measured sample count, rolling average/max, session max, invalid-stamp count, reset behavior, and truthful UI states. Keep transport telemetry unchanged. | pending | `addon/telemetry.py`; `addon/ui.py`; `tests/test_telemetry.py` | pending |
| T3 | Extend the installed-Start proof to record and validate camera-to-rig latency as a distinct measured field, update the milestone/roadmap wording, then run focused, canonical, and one exclusive live proof. | pending | `tools/blender_start_proof.py`; `tests/test_blender_start_proof.py`; `docs/roadmap.md`; `odd/tasks/milestone-closure-m0-m1.md`; this file | pending |

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
- Commit: pending creation in this work unit.

T2 and T3 evidence will be appended when each task closes.

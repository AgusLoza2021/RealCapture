"""Camera acquisition stamp correlation for the MediaPipe backend (T1).

Pure tests: no cv2, no mediapipe. ``MediaPipeBackend.__init__`` performs no
heavy imports, so instances are built directly; the async result callback and
the drain/send path are driven by hand with stub result objects.

Covered behavior:
- the acquisition stamp sampled after a successful ``cap.read()`` travels to
  the exact async callback result (keyed by the callback's ``timestamp_ms``),
- out-of-order callbacks each keep their own stamp,
- missing or evicted correlations never fabricate a stamp,
- pending state is bounded with deterministic (oldest-first) eviction.

The failed-``cap.read()`` path cannot be exercised without stubbing the whole
cv2/mediapipe module surface inside ``run_loop`` (overmocking), so it is
covered structurally: the stamp is sampled after the ``if not ok: continue``
guard, and every correlation below goes through the same
``_register_pending`` entry point the success path uses.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.backends import mediapipe_backend as mpb
from backend.backends.mediapipe_backend import MAX_PENDING_STAMPS, MediaPipeBackend


def _face_result(with_face: bool = True):
    """A stub shaped like a mediapipe FaceLandmarkerResult."""
    if not with_face:
        return SimpleNamespace(face_blendshapes=[], facial_transformation_matrixes=[])
    return SimpleNamespace(
        face_blendshapes=[[SimpleNamespace(category_name="jawOpen", score=0.5)]],
        facial_transformation_matrixes=[],
    )


def _backend_with_captured_sends():
    backend = MediaPipeBackend()
    sent: list = []
    backend.send_packet = sent.append  # instance override; no UDP socket in tests
    return backend, sent


def _deliver_and_drain(backend, result, timestamp_ms):
    backend._on_result(result, None, timestamp_ms)
    backend._drain_and_send()


def test_exact_stamp_travels_to_the_emitted_packet():
    backend, sent = _backend_with_captured_sends()

    backend._register_pending(1000, 1_700_000_000_123)
    _deliver_and_drain(backend, _face_result(), 1000)

    assert len(sent) == 1
    packet = sent[0]
    assert packet.extra["acq_t_ms"] == 1_700_000_000_123
    assert isinstance(packet.extra["acq_t_ms"], int)
    # Requirement 4: packet.t stays the post-inference epoch ms.
    assert isinstance(packet.t, int)


def test_no_face_result_emits_no_packet():
    backend, sent = _backend_with_captured_sends()

    backend._register_pending(1000, 1_700_000_000_123)
    _deliver_and_drain(backend, _face_result(with_face=False), 1000)

    assert sent == []


def test_out_of_order_callbacks_keep_their_own_stamps():
    backend, sent = _backend_with_captured_sends()

    backend._register_pending(1000, 1_700_000_000_100)
    backend._register_pending(2000, 1_700_000_000_200)

    # Callbacks arrive in reverse submission order.
    _deliver_and_drain(backend, _face_result(), 2000)
    _deliver_and_drain(backend, _face_result(), 1000)

    assert [p.extra["acq_t_ms"] for p in sent] == [1_700_000_000_200, 1_700_000_000_100]


def test_missing_correlation_does_not_fabricate_a_stamp():
    backend, sent = _backend_with_captured_sends()

    # Callback for a timestamp that was never registered (dropped frame path).
    _deliver_and_drain(backend, _face_result(), 4242)

    assert len(sent) == 1
    assert "acq_t_ms" not in sent[0].extra
    # Requirement 4: the post-inference timestamp is untouched.
    assert isinstance(sent[0].t, int)


def test_evicted_correlation_does_not_fabricate_a_stamp():
    backend, sent = _backend_with_captured_sends()

    # One more registration than the named limit evicts the oldest entry.
    for ts in range(MAX_PENDING_STAMPS + 1):
        backend._register_pending(ts, 1_000_000 + ts)

    _deliver_and_drain(backend, _face_result(), 0)  # oldest: evicted
    _deliver_and_drain(backend, _face_result(), MAX_PENDING_STAMPS)  # newest: kept

    assert len(sent) == 2
    assert "acq_t_ms" not in sent[0].extra, "evicted correlation must not fabricate a stamp"
    assert sent[1].extra["acq_t_ms"] == 1_000_000 + MAX_PENDING_STAMPS


def test_pending_state_is_bounded():
    backend = MediaPipeBackend()

    for ts in range(MAX_PENDING_STAMPS + 10):
        backend._register_pending(ts, ts)

    assert len(backend._pending_acq) == MAX_PENDING_STAMPS
    assert 0 not in backend._pending_acq, "oldest entry must be evicted first"
    assert MAX_PENDING_STAMPS + 9 in backend._pending_acq


def test_pending_state_does_not_leak_after_normal_correlation():
    backend = MediaPipeBackend()

    backend._register_pending(1000, 1_700_000_000_123)
    backend._on_result(_face_result(), None, 1000)

    assert backend._pending_acq == {}


def test_the_named_limit_is_explicit_and_positive():
    # ``type(...) is int`` rejects bool: True/False are int subclasses and
    # must not pass as the named limit.
    assert type(MAX_PENDING_STAMPS) is int
    assert MAX_PENDING_STAMPS > 0


class _RecordingLandmarker:
    """Fake landmarker that snapshots pending correlation at submission time."""

    def __init__(self, backend):
        self._backend = backend
        self.submissions: list[tuple] = []  # (image, timestamp_ms, pending snapshot)

    def detect_async(self, mp_image, timestamp_ms):  # noqa: ANN001 - test stub
        self.submissions.append((mp_image, timestamp_ms, dict(self._backend._pending_acq)))


def test_submission_path_registers_the_exact_timestamp_before_detect_async():
    backend, sent = _backend_with_captured_sends()
    landmarker = _RecordingLandmarker(backend)

    ts = backend._submit_frame(landmarker, "rgb-frame", 1_700_000_000_123)

    assert len(landmarker.submissions) == 1
    image, submitted_ts, pending_at_submit = landmarker.submissions[0]
    assert image == "rgb-frame"
    # The timestamp handed to detect_async IS the correlation key.
    assert submitted_ts == ts
    # Registration strictly preceded the async submission and carries this
    # frame's acquisition stamp.
    assert pending_at_submit.get(ts) == 1_700_000_000_123

    # Full chain: the callback fired with that timestamp correlates exactly.
    backend._on_result(_face_result(), None, ts)
    backend._drain_and_send()
    assert sent[0].extra["acq_t_ms"] == 1_700_000_000_123


def test_sample_acq_stamp_is_epoch_time_not_monotonic(monkeypatch):
    # Both clocks are pinned to different sentinels: an epoch implementation
    # answers the time.time sentinel; a monotonic replacement cannot.
    monkeypatch.setattr(mpb.time, "time", lambda: 1_234_567_890.5)
    monkeypatch.setattr(mpb.time, "monotonic", lambda: 42.0)

    backend = MediaPipeBackend()

    assert backend._sample_acq_t_ms() == 1_234_567_890_500


def test_no_face_callback_still_consumes_its_pending_correlation():
    backend = MediaPipeBackend()

    backend._register_pending(1000, 1_700_000_000_123)
    backend._on_result(_face_result(with_face=False), None, 1000)

    # No packet is emitted, but the correlation must not linger.
    assert backend._pending_acq == {}

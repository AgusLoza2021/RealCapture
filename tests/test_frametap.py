"""Tests for the bounded latest-frame tap (no cv2, no numpy, no camera)."""

from __future__ import annotations

from backend.backends.base import CaptureBackend
from backend.dashboard.frametap import (
    MAX_STREAM_FPS,
    MIN_STREAM_FPS,
    FrameTap,
    clamp_stream_fps,
    should_encode,
)


class TestLatestWins:
    def test_peek_before_any_publish_is_none(self) -> None:
        tap = FrameTap()
        assert tap.peek() is None

    def test_many_publishes_retain_exactly_one_frame_and_it_is_the_newest(self) -> None:
        tap = FrameTap()
        frames = [object() for _ in range(1000)]
        for index, frame in enumerate(frames):
            tap.publish(frame, float(index))
        current = tap.peek()
        assert current is not None
        frame, t = current
        assert frame is frames[-1]
        assert t == 999.0
        # Bounded slot: no older frame survives in the tap.
        assert frame is not frames[0]
        assert frame is not frames[499]

    def test_peek_does_not_consume_the_frame(self) -> None:
        tap = FrameTap()
        frame = object()
        tap.publish(frame, 1.0)
        assert tap.peek() is tap.peek()

    def test_publish_overwrites_timestamp_alongside_frame(self) -> None:
        tap = FrameTap()
        tap.publish("a", 1.0)
        tap.publish("b", 2.5)
        assert tap.peek() == ("b", 2.5)


class TestSubscriberBookkeeping:
    def test_count_starts_at_zero_and_tracks_registration(self) -> None:
        tap = FrameTap()
        assert tap.subscriber_count == 0
        unsubscribe = tap.subscribe()
        assert tap.subscriber_count == 1
        unsubscribe()
        assert tap.subscriber_count == 0

    def test_unsubscribe_is_idempotent(self) -> None:
        tap = FrameTap()
        unsubscribe = tap.subscribe()
        unsubscribe()
        unsubscribe()
        assert tap.subscriber_count == 0

    def test_two_subscribers_unregister_independently(self) -> None:
        tap = FrameTap()
        first = tap.subscribe()
        second = tap.subscribe()
        assert tap.subscriber_count == 2
        first()
        assert tap.subscriber_count == 1
        second()
        assert tap.subscriber_count == 0


class TestEncodeGate:
    """The idle = no encode rule: the behaviour that most easily regresses."""

    MIN_INTERVAL = 1.0 / 12.0

    def test_zero_subscribers_never_encodes(self) -> None:
        assert should_encode(100.0, None, 0, self.MIN_INTERVAL) is False
        assert should_encode(100.0, 99.0, 0, self.MIN_INTERVAL) is False

    def test_inside_minimum_interval_is_false(self) -> None:
        assert should_encode(1.0, 0.99, 1, self.MIN_INTERVAL) is False

    def test_outside_minimum_interval_with_subscriber_is_true(self) -> None:
        assert should_encode(1.0, 0.0, 1, self.MIN_INTERVAL) is True

    def test_first_frame_with_subscriber_is_true(self) -> None:
        assert should_encode(1.0, None, 1, self.MIN_INTERVAL) is True

    def test_exact_boundary_counts_as_outside(self) -> None:
        assert should_encode(1.0, 1.0 - self.MIN_INTERVAL, 1, self.MIN_INTERVAL) is True


class TestRateCap:
    def test_cap_is_15_fps(self) -> None:
        assert MAX_STREAM_FPS == 15

    def test_cap_cannot_be_raised_from_outside(self) -> None:
        assert clamp_stream_fps(1000) == MAX_STREAM_FPS
        assert clamp_stream_fps(MAX_STREAM_FPS + 0.001) == MAX_STREAM_FPS

    def test_clamp_keeps_sane_values_and_floors_broken_ones(self) -> None:
        assert clamp_stream_fps(12) == 12
        assert clamp_stream_fps(MIN_STREAM_FPS) == MIN_STREAM_FPS
        assert clamp_stream_fps(0) == MIN_STREAM_FPS
        assert clamp_stream_fps(-3) == MIN_STREAM_FPS


class TestInjectedEncoder:
    def test_encode_frame_uses_the_injected_encoder(self) -> None:
        calls: list = []

        def encode(frame: object) -> bytes:
            calls.append(frame)
            return b"jpeg"

        tap = FrameTap(encode=encode)
        assert tap.encode_frame(b"x") == b"jpeg"
        assert tap.encode_frame(b"y") == b"jpeg"
        assert calls == [b"x", b"y"]

    def test_encode_frame_without_encoder_returns_none(self) -> None:
        assert FrameTap().encode_frame(object()) is None


class _DummyBackend(CaptureBackend):
    backend_name = "dummy"

    def run_loop(self) -> None:  # pragma: no cover - never executed in tests
        raise AssertionError("run_loop must not run in tests")


class TestNotifyFrameHook:
    def test_callback_receives_frame_and_a_timestamp(self) -> None:
        backend = _DummyBackend()
        seen: list = []
        backend.on_frame = lambda frame, t: seen.append((frame, t))
        frame = object()
        backend.notify_frame(frame)
        assert len(seen) == 1
        assert seen[0][0] is frame
        assert isinstance(seen[0][1], float)

    def test_raising_callback_never_escapes_into_the_capture_loop(self) -> None:
        backend = _DummyBackend()

        def bad(frame: object, t: float) -> None:
            raise RuntimeError("observer exploded")

        backend.on_frame = bad
        backend.notify_frame(object())  # must not raise

    def test_no_observer_is_a_noop(self) -> None:
        backend = _DummyBackend()
        backend.notify_frame(object())  # must not raise

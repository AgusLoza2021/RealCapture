"""Tests for the MJPEG camera stream endpoint (fake encoder, no cv2, no camera)."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from backend.dashboard.frametap import FrameTap  # noqa: E402
from backend.dashboard.hub import BroadcastHub, DashboardHub  # noqa: E402
from backend.dashboard.server import create_app, encode_or_reason  # noqa: E402

FAKE_JPEG = b"\xff\xd8\xff\xd9"


class CountingEncoder:
    """Fake JPEG encoder: returns a minimal JPEG-looking payload and counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, frame: object) -> bytes:
        self.calls += 1
        return FAKE_JPEG


class RaisingEncoder:
    """Encoder that always raises, standing in for a missing cv2 import."""

    def __call__(self, frame: object) -> bytes:
        raise ImportError("No module named 'cv2'")


def _app_with_tap(tap: FrameTap, **kwargs) -> object:
    return create_app(DashboardHub(), BroadcastHub(), frame_tap=tap, **kwargs)


class TestCameraStreamHonesty:
    def test_no_tap_bound_answers_503_with_reason_not_a_stream(self) -> None:
        app = create_app(DashboardHub(), BroadcastHub())
        client = TestClient(app)
        response = client.get("/camera.mjpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert "frame tap" in response.text
        client.close()

    def test_tap_without_published_frames_answers_503(self) -> None:
        tap = FrameTap(encode=CountingEncoder())
        client = TestClient(_app_with_tap(tap))
        response = client.get("/camera.mjpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert "frame" in response.text
        client.close()


class TestCameraStream:
    # The bundled TestClient buffers the whole body before returning, so the
    # streaming generator runs to completion inside the request. A short idle
    # timeout ends the stream deterministically once frames stop arriving.
    STREAM_IDLE = 0.1

    def test_published_frame_streams_mjpeg_with_jpeg_magic(self) -> None:
        encoder = CountingEncoder()
        tap = FrameTap(encode=encoder)
        tap.publish(b"raw-bgr-frame", 1.0)
        client = TestClient(_app_with_tap(tap, stream_idle_timeout_s=self.STREAM_IDLE))
        with client.stream("GET", "/camera.mjpg") as response:
            assert response.status_code == 200
            assert "multipart/x-mixed-replace" in response.headers["content-type"]
            body = b""
            for chunk in response.iter_raw():
                body += chunk
        assert b"\xff\xd8" in body
        assert encoder.calls >= 1
        client.close()

    def test_subscriber_count_returns_to_zero_after_the_stream_ends(self) -> None:
        tap = FrameTap(encode=CountingEncoder())
        tap.publish(b"raw-bgr-frame", 1.0)
        client = TestClient(_app_with_tap(tap, stream_idle_timeout_s=self.STREAM_IDLE))
        with client.stream("GET", "/camera.mjpg") as response:
            for chunk in response.iter_raw():
                pass
        # The generator's finally unregistered the consumer: no phantom subscriber.
        assert tap.subscriber_count == 0
        client.close()


class TestCameraStreamEncodingHonesty:
    """A stream must never commit 200 and then produce zero bytes."""

    def test_no_encoder_bound_answers_503_not_an_empty_stream(self) -> None:
        tap = FrameTap()  # constructed without an encoder: _encode is None
        tap.publish(b"raw-bgr-frame", 1.0)
        client = TestClient(_app_with_tap(tap))
        response = client.get("/camera.mjpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert response.text == "camera stream unavailable: no JPEG encoder is bound to the frame tap"
        client.close()

    def test_raising_encoder_stream_answers_503_naming_the_failure(self) -> None:
        tap = FrameTap(encode=RaisingEncoder())
        tap.publish(b"raw-bgr-frame", 1.0)
        client = TestClient(_app_with_tap(tap))
        response = client.get("/camera.mjpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert response.text == (
            "camera stream unavailable: JPEG encoding failed: ImportError: No module named 'cv2'"
        )
        client.close()

    def test_raising_encoder_one_shot_answers_503_naming_the_failure(self) -> None:
        tap = FrameTap(encode=RaisingEncoder())
        tap.publish(b"raw-bgr-frame", 1.0)
        client = TestClient(_app_with_tap(tap))
        response = client.get("/camera.jpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert response.text == (
            "camera snapshot unavailable: JPEG encoding failed: ImportError: No module named 'cv2'"
        )
        client.close()


class TestEncodeOrReason:
    def test_success_returns_bytes_and_none(self) -> None:
        tap = FrameTap(encode=CountingEncoder())
        data, reason = encode_or_reason(tap, b"raw-bgr-frame")
        assert data == FAKE_JPEG
        assert reason is None

    def test_unbound_encoder_returns_reason_naming_the_missing_thing(self) -> None:
        tap = FrameTap()
        data, reason = encode_or_reason(tap, b"raw-bgr-frame")
        assert data is None
        assert reason == "no JPEG encoder is bound to the frame tap"

    def test_raising_encoder_returns_reason_with_exception_class_name(self) -> None:
        tap = FrameTap(encode=RaisingEncoder())
        data, reason = encode_or_reason(tap, b"raw-bgr-frame")
        assert data is None
        assert reason is not None
        assert "ImportError" in reason


class TestCameraOneShot:
    def test_no_tap_bound_answers_503_with_reason(self) -> None:
        app = create_app(DashboardHub(), BroadcastHub())
        client = TestClient(app)
        response = client.get("/camera.jpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert "frame tap" in response.text
        client.close()

    def test_tap_without_published_frames_answers_503(self) -> None:
        tap = FrameTap(encode=CountingEncoder())
        client = TestClient(_app_with_tap(tap))
        response = client.get("/camera.jpg")
        assert response.status_code == 503
        assert "text/plain" in response.headers["content-type"]
        assert "frame" in response.text
        client.close()

    def test_published_frame_returns_single_jpeg_no_store(self) -> None:
        encoder = CountingEncoder()
        tap = FrameTap(encode=encoder)
        tap.publish(b"raw-bgr-frame", 1.0)
        client = TestClient(_app_with_tap(tap))
        response = client.get("/camera.jpg")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "no-store"
        assert response.content == FAKE_JPEG
        assert encoder.calls == 1  # one shot: exactly one encode, no gate, no subscription
        assert tap.subscriber_count == 0
        client.close()

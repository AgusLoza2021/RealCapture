"""Bounded latest-frame tap between the capture loop and the camera preview.

This module is deliberately free of cv2 and numpy: frames are opaque objects
handed over by the capture loop, and JPEG encoding is injected as a callable,
so the whole tap is unit-testable without any image library or real camera.

Bounded by construction: the tap holds exactly one frame in a size-1 slot
guarded by a lock. ``publish`` replaces whatever was there, so a slow or
absent consumer can never queue frames — publishing a thousand frames retains
exactly one (the newest), never more.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional, Tuple

#: Hard cap for the preview stream rate, in frames per second. Callers may
#: request less through :func:`clamp_stream_fps` but never more than this.
MAX_STREAM_FPS = 15.0

#: Floor for the stream rate so a typo like ``--stream-fps 0`` cannot stall it.
MIN_STREAM_FPS = 1.0

#: A JPEG encoder: opaque frame in, encoded bytes out.
EncodeFn = Callable[[Any], bytes]


def should_encode(
    now: float,
    last_encode_t: Optional[float],
    subscriber_count: int,
    min_interval_s: float,
) -> bool:
    """Pure encode gate for the camera preview.

    Idle means no encode: with zero subscribers this always returns False,
    regardless of the interval. Inside the minimum interval it returns False.
    Otherwise (someone is watching and enough time has passed) it returns True.
    """
    if subscriber_count <= 0:
        return False
    if last_encode_t is None:
        return True
    return (now - last_encode_t) >= min_interval_s


def clamp_stream_fps(requested: float) -> float:
    """Clamp a caller-requested stream fps into [MIN_STREAM_FPS, MAX_STREAM_FPS]."""
    return max(MIN_STREAM_FPS, min(float(requested), MAX_STREAM_FPS))


class FrameTap:
    """Size-1 latest-wins frame slot with subscriber bookkeeping.

    The capture loop calls :meth:`publish` once per captured frame; the stream
    endpoint subscribes while a browser is watching and unsubscribes when it
    disconnects, so :attr:`subscriber_count` answers "is anyone watching?".
    """

    def __init__(self, encode: Optional[EncodeFn] = None) -> None:
        self._lock = threading.Lock()
        self._slot: Optional[Tuple[Any, float]] = None
        self._subscribers: set[int] = set()
        self._next_token = 0
        self._encode = encode

    # -- frame slot ----------------------------------------------------------

    def publish(self, frame: Any, t: float) -> None:
        """Replace the slot with the newest frame; older frames are dropped."""
        with self._lock:
            self._slot = (frame, t)

    def peek(self) -> Optional[Tuple[Any, float]]:
        """Return ``(frame, timestamp)`` of the newest frame, or None."""
        with self._lock:
            return self._slot

    # -- subscribers ---------------------------------------------------------

    def subscribe(self) -> Callable[[], None]:
        """Register a consumer; returns its unsubscribe callable."""
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._subscribers.add(token)

        def unsubscribe() -> None:
            self.unsubscribe_token(token)

        return unsubscribe

    def unsubscribe_token(self, token: int) -> None:
        with self._lock:
            self._subscribers.discard(token)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # -- encoding ------------------------------------------------------------

    def encode_frame(self, frame: Any) -> Optional[bytes]:
        """Encode a frame with the injected encoder (None when unbound)."""
        if self._encode is None:
            return None
        return self._encode(frame)

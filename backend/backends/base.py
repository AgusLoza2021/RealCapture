"""Abstract capture backend interface.

Contract:
- Backends run in their own OS process (never inside Blender); threads are safe here.
- Latest-frame-wins: when the consumer is slower than the producer, older frames
  are dropped, never queued.
- Network sends are best-effort: a failed send is logged and skipped, it never
  stops the capture loop.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable

from ..common.packets import Packet

logger = logging.getLogger(__name__)

DEFAULT_UDP_HOST = "127.0.0.1"
DEFAULT_UDP_PORT = 11111
DEFAULT_FPS = 30


class BackendImportError(RuntimeError):
    """Raised when a backend's heavy dependencies are missing."""


class CaptureBackend(ABC):
    """Base class for RealCapture capture engines.

    Subclasses implement :meth:`run_loop`, which must:
    - return promptly when ``self._stop_event.is_set()``,
    - produce validated :class:`Packet` objects and hand them to
      :meth:`send_packet` (best-effort),
    - never queue frames (drop instead).
    """

    backend_name: str = "abstract"

    def __init__(
        self,
        camera_index: int = 0,
        fps: int = DEFAULT_FPS,
        udp_host: str = DEFAULT_UDP_HOST,
        udp_port: int = DEFAULT_UDP_PORT,
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be positive")
        self.camera_index = camera_index
        self.fps = fps
        self.udp_host = udp_host
        self.udp_port = udp_port
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._packets_sent = 0
        self._send_errors = 0
        # Optional dashboard hooks (see backend/dashboard/hub.py). Called from
        # the capture thread; must never raise into the capture loop.
        self.on_packet: Callable[[Packet, float], None] | None = None
        self.on_send_error: Callable[[], None] | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Open the UDP socket and start the capture loop thread."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("backend already started")
        self._stop_event.clear()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._thread = threading.Thread(
            target=self._guarded_loop, name=f"realcapture-{self.backend_name}", daemon=True
        )
        self._thread.start()
        logger.info(
            "%s backend started (camera=%d fps=%d -> udp %s:%d)",
            self.backend_name,
            self.camera_index,
            self.fps,
            self.udp_host,
            self.udp_port,
        )

    def stop(self) -> None:
        """Signal the loop to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        logger.info("%s backend stopped", self.backend_name)

    def __enter__(self) -> "CaptureBackend":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    @property
    def running(self) -> bool:
        return not self._stop_event.is_set()

    @property
    def is_alive(self) -> bool:
        """True while the capture thread is running or not yet finished."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def packets_sent(self) -> int:
        return self._packets_sent

    @property
    def send_errors(self) -> int:
        return self._send_errors

    # -- to be implemented by subclasses -------------------------------------

    @abstractmethod
    def run_loop(self) -> None:
        """Capture loop body. Must observe self._stop_event and return promptly."""

    # -- helpers for subclasses ----------------------------------------------

    def _guarded_loop(self) -> None:
        try:
            self.run_loop()
        except Exception:  # noqa: BLE001 - keep process alive, log full context
            logger.exception("capture loop crashed in %s backend", self.backend_name)

    def send_packet(self, packet: Packet) -> None:
        """Best-effort UDP send; never raises into the capture loop."""
        if self._socket is None:
            return
        from ..common.packets import encode_packet

        started = time.perf_counter()
        try:
            payload = encode_packet(
                t=packet.t,
                engine=packet.engine,
                conf=packet.conf,
                pose=packet.pose,
                shapes=packet.shapes,
                extra=packet.extra,
            )
            self._socket.sendto(payload, (self.udp_host, self.udp_port))
            self._packets_sent += 1
            if self.on_packet is not None:
                proc_ms = (time.perf_counter() - started) * 1000.0
                try:
                    self.on_packet(packet, proc_ms)
                except Exception:  # noqa: BLE001 - observer must not break capture
                    logger.exception("on_packet observer failed")
        except OSError as exc:
            self._send_errors += 1
            if self.on_send_error is not None:
                try:
                    self.on_send_error()
                except Exception:  # noqa: BLE001
                    logger.exception("on_send_error observer failed")
            if self._send_errors <= 5 or self._send_errors % 500 == 0:
                logger.warning("UDP send failed (%d so far): %s", self._send_errors, exc)

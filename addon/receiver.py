"""Pure UDP receiver: non-blocking drain, latest-frame-wins.

No bpy imports here on purpose: this logic runs under pytest and could later
be reused by other consumers. All Blender interaction lives in consumer.py.
"""

from __future__ import annotations

import socket

from .schema import Packet, PacketValidationError, decode_packet

DEFAULT_MAX_DRAIN = 64


class UdpReceiver:
    """Binds a UDP socket and yields only the newest valid packet per poll.

    Stale queued datagrams are discarded: for facial animation, an old frame is
    worse than a dropped frame. Only the NEWEST datagram is decoded (decode
    cost stays constant per poll); if it fails validation it is counted in
    ``invalid_count`` and poll returns None. Stale datagrams are never decoded,
    so invalid ones among them are not counted -- but every stale discard is
    counted in the cumulative ``stale_dropped`` counter, so throttling and
    loss stay observable. ``reset_counters()`` zeroes both cumulative counters.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 11111, max_drain: int = DEFAULT_MAX_DRAIN) -> None:
        if port < 0 or port > 65535:
            raise ValueError(f"invalid UDP port: {port}")
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.setblocking(False)
        self._max_drain = max_drain
        self.invalid_count = 0
        self.stale_dropped = 0

    @property
    def bound_port(self) -> int:
        return self._sock.getsockname()[1]

    def poll_latest(self) -> Packet | None:
        """Drain the socket queue; decode and return the newest packet, or None.

        Every drained datagram replaced by a newer one increments the
        cumulative ``stale_dropped`` counter; a poll that drains one or zero
        datagrams discards nothing.
        """
        newest: bytes | None = None
        drained = 0
        for _ in range(self._max_drain):
            try:
                data, _addr = self._sock.recvfrom(65535)
            except BlockingIOError:
                break
            newest = data
            drained += 1
        if newest is None:
            return None
        if drained > 1:
            self.stale_dropped += drained - 1
        try:
            return decode_packet(newest)
        except PacketValidationError:
            self.invalid_count += 1
            return None

    def reset_counters(self) -> None:
        """Zero both cumulative counters (invalid_count, stale_dropped)."""
        self.invalid_count = 0
        self.stale_dropped = 0

    def close(self) -> None:
        self._sock.close()

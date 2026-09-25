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
    so invalid ones among them are not counted.
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

    @property
    def bound_port(self) -> int:
        return self._sock.getsockname()[1]

    def poll_latest(self) -> Packet | None:
        """Drain the socket queue; decode and return the newest packet, or None."""
        newest: bytes | None = None
        for _ in range(self._max_drain):
            try:
                data, _addr = self._sock.recvfrom(65535)
            except BlockingIOError:
                break
            newest = data
        if newest is None:
            return None
        try:
            return decode_packet(newest)
        except PacketValidationError:
            self.invalid_count += 1
            return None

    def close(self) -> None:
        self._sock.close()

"""Blender heartbeat: freshness tracker plus the non-blocking read path.

The addon answers each received packet with a small heartbeat datagram back
to the address ``recvfrom`` already produced (same socket pair, no new
port, no handshake). This module owns the backend end of that channel:

- :class:`HeartbeatTracker` keeps the interpretation-free facts (last
  arrival, revision, bind report). The truth table that maps heartbeat age
  to green/yellow/red lives in the connection model (W4), not here.
- :func:`parse_heartbeat` validates the datagram shape. A datagram without
  the ``rc_heartbeat`` discriminator or with wrong types is rejected, never
  guessed at -- and every rejection is counted in
  ``HeartbeatTracker.invalid_count`` (a counter that is never incremented
  is a defect).
- :class:`HeartbeatReader` drains the backend's send socket without ever
  blocking or raising: reading must never delay a packet send.

Thread model: the capture thread calls ``observe``/``poll`` (via the
``send_packet`` path); the web server thread reads ``age_s`` /
``bind_report`` / ``revision``. Field updates are single attribute writes,
safe under the GIL for these readers.
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any

#: The discriminator: an unrelated datagram must be rejected, not guessed at.
DISCRIMINATOR = "rc_heartbeat"

BIND_MODES = ("shape_keys", "point_bones", "none")

SKIP_REASONS = ("no_armature", "no_head_bone", "rest_gate")

KNOWN_TOP_LEVEL_FIELDS = frozenset({DISCRIMINATOR, "t_send_ms", "revision", "bind"})

RECV_BUF = 65535

#: Upper bound per poll: heartbeats arrive at ~2 Hz, so the queue cannot
#: build up; the bound only caps the worst case.
MAX_DRAIN = 16


class HeartbeatValidationError(ValueError):
    """Raised when a datagram is not a valid heartbeat."""


def _check_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HeartbeatValidationError(f"{where} must be an integer, got {type(value).__name__}")
    if value < 0:
        raise HeartbeatValidationError(f"{where} must be >= 0, got {value}")
    return value


def _check_optional_str(value: Any, where: str) -> Any:
    if value is None or isinstance(value, str):
        return value
    raise HeartbeatValidationError(f"{where} must be a string or null, got {type(value).__name__}")


def _check_optional_number(value: Any, where: str) -> Any:
    if value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return value
    raise HeartbeatValidationError(f"{where} must be a number or null, got {type(value).__name__}")


def parse_heartbeat(data: bytes) -> dict:
    """Validate a heartbeat datagram and return the parsed payload.

    Raises HeartbeatValidationError on any schema violation: a datagram
    without ``rc_heartbeat == 1``, with wrong types, or with unknown
    top-level fields is rejected, never guessed at.
    """
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HeartbeatValidationError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise HeartbeatValidationError(f"heartbeat must be a JSON object, got {type(raw).__name__}")

    unknown = set(raw) - KNOWN_TOP_LEVEL_FIELDS
    if unknown:
        raise HeartbeatValidationError(f"unknown heartbeat fields: {sorted(unknown)}")
    if raw.get(DISCRIMINATOR) != 1 or isinstance(raw.get(DISCRIMINATOR), bool):
        raise HeartbeatValidationError("missing or wrong rc_heartbeat discriminator")

    _check_int(raw.get("t_send_ms"), "t_send_ms")
    _check_int(raw.get("revision"), "revision")

    bind = raw.get("bind")
    if bind is not None:
        if not isinstance(bind, dict):
            raise HeartbeatValidationError("bind must be an object or null")
        mode = bind.get("mode")
        if not isinstance(mode, str) or mode not in BIND_MODES:
            raise HeartbeatValidationError(f"bind.mode must be one of {BIND_MODES}")
        _check_int(bind.get("channels"), "bind.channels")
        _check_optional_str(bind.get("head_bone"), "bind.head_bone")
        _check_optional_number(bind.get("rest_displacement_m"), "bind.rest_displacement_m")
        _check_optional_number(
            bind.get("refused_rest_displacement_m"), "bind.refused_rest_displacement_m"
        )
        skip_reason = bind.get("skip_reason")
        if skip_reason is not None and (
                not isinstance(skip_reason, str) or skip_reason not in SKIP_REASONS):
            raise HeartbeatValidationError(
                f"bind.skip_reason must be one of {SKIP_REASONS} or null")
    return raw


class HeartbeatTracker:
    """Freshness and bind-report state for the Blender back-channel."""

    def __init__(self) -> None:
        self.invalid_count = 0
        self.revision: int | None = None
        self._last_arrival_s: float | None = None
        self._bind: dict | None = None

    def observe(self, data: bytes, arrival_s: float | None = None) -> bool:
        """Parse, validate, and record one raw datagram.

        Returns True when the datagram was accepted; a rejection is counted
        in ``invalid_count`` and leaves the previous state untouched.
        """
        try:
            payload = parse_heartbeat(data)
        except HeartbeatValidationError:
            self.invalid_count += 1
            return False
        self.record(payload, arrival_s)
        return True

    def record(self, payload: dict, arrival_s: float | None = None) -> None:
        """Record one already-parsed payload with its arrival (monotonic) time."""
        self._last_arrival_s = time.monotonic() if arrival_s is None else arrival_s
        self.revision = payload["revision"]
        self._bind = dict(payload["bind"]) if isinstance(payload["bind"], dict) else None

    def age_s(self, now: float | None = None) -> float | None:
        """Seconds since the last accepted heartbeat; None means never."""
        if self._last_arrival_s is None:
            return None
        return (time.monotonic() if now is None else now) - self._last_arrival_s

    def bind_report(self) -> dict | None:
        """The bind report exactly as the addon sent it, or None."""
        return dict(self._bind) if self._bind is not None else None


class HeartbeatReader:
    """Drains heartbeat datagrams off the backend's send socket. Never raises."""

    def __init__(self, tracker: HeartbeatTracker) -> None:
        self._tracker = tracker

    def poll(self, sock: socket.socket) -> int:
        """Read every queued datagram (bounded); return how many were accepted.

        Non-blocking and exception-free by contract: the caller runs this on
        the packet send path, and a read must never delay or break a send.
        Rejections are counted in the tracker's ``invalid_count``.
        """
        accepted = 0
        for _ in range(MAX_DRAIN):
            try:
                data, _addr = sock.recvfrom(RECV_BUF)
            except BlockingIOError:
                break
            except OSError:
                break  # closed or reset socket: nothing readable this poll
            if self._tracker.observe(data):
                accepted += 1
        return accepted

"""Blender back-channel: best-effort heartbeat replies on the receive socket.

No bpy imports here on purpose: the datagram builder and the sender run
under pytest, and consumer.py (the only bpy-side caller) wires them into
its timer tick. The heartbeat answers the address ``recvfrom`` already
returned: the reply travels back on the SAME socket the packets arrived
on, with no new port and no handshake.

Wire shape (frozen contract, odd/tasks/control-room-window.md):

    {"rc_heartbeat": 1, "t_send_ms": <int>, "revision": <int>,
     "bind": {"mode": "shape_keys|point_bones|none", "channels": <int>,
              "head_bone": <str|null>,
              "rest_displacement_m": <float|null>,          <- the bind IN EFFECT
              "refused_rest_displacement_m": <float|null>,  <- the rejected point/bone attempt
              "skip_reason": "no_armature|no_head_bone|rest_gate"|null} | null}

``rest_displacement_m`` and ``refused_rest_displacement_m`` are DIFFERENT
numbers: the first is the health of the bind actually in effect (the revert
residual after a refusal), the second is the damage of the refused attempt.
Conflating them paints a working rig as degraded forever.

The datagram stays under MAX_HEARTBEAT_BYTES; when the bind report would
exceed that, detail is dropped rather than splitting the message.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

#: Hard byte ceiling for one heartbeat datagram (safe for any UDP path).
MAX_HEARTBEAT_BYTES = 1200

#: Minimum spacing between two heartbeat attempts (~2 Hz cadence cap).
MIN_SEND_INTERVAL_S = 0.5

HEARTBEAT_DISCRIMINATOR = "rc_heartbeat"


def build_heartbeat(bind: dict | None, t_send_ms: int, revision: int) -> bytes:
    """Serialize one heartbeat datagram as compact UTF-8 JSON.

    When the bind report does not fit under MAX_HEARTBEAT_BYTES, detail is
    dropped first (head_bone, rest_displacement_m), then the whole bind;
    the message itself is never split and the discriminator is always
    present.
    """
    payload = {
        HEARTBEAT_DISCRIMINATOR: 1,
        "t_send_ms": int(t_send_ms),
        "revision": int(revision),
        "bind": bind,
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= MAX_HEARTBEAT_BYTES:
        return encoded
    if isinstance(bind, dict):
        # Drop the detail, keep the identity: mode + channel count.
        slim = dict(payload, bind={"mode": bind.get("mode"), "channels": bind.get("channels")})
        encoded = json.dumps(slim, separators=(",", ":")).encode("utf-8")
        if len(encoded) <= MAX_HEARTBEAT_BYTES:
            return encoded
    return json.dumps(dict(payload, bind=None), separators=(",", ":")).encode("utf-8")


def summarize_bind(
    bone_path_active: bool,
    has_shape_entries: bool,
    head_bone: str | None,
    attempt_rest_displacement_m: float | None,
    residual_rest_displacement_m: float | None,
    skip_reason: str | None,
    channels: int,
) -> dict:
    """Build the bind report dict from values the bind layer already knows.

    ``rest_displacement_m`` is the bind IN EFFECT: the attempt measurement
    while the bone path drives, the revert residual after a refusal, and
    null when no bone path was involved at all. The refused attempt
    travels separately in ``refused_rest_displacement_m`` so a refused
    bind is never mistaken for the health of the bind in effect.
    ``skip_reason`` passes through as-is (None when the bone path is live
    or the profile had no points/bone bindings).

    ``head_bone`` is reported only while the bone path actually drives the
    rig; a rejected or torn-down bone path reports None even though a
    candidate bone name was resolved (the refused displacement and the
    skip reason tell that story instead).
    """
    mode = "point_bones" if bone_path_active else ("shape_keys" if has_shape_entries else "none")
    if bone_path_active:
        rest = attempt_rest_displacement_m
        refused = None  # nothing was refused: the attempt IS the bind
    elif skip_reason is not None:
        rest = residual_rest_displacement_m
        refused = attempt_rest_displacement_m
    else:
        rest = None
        refused = None
    return {
        "mode": mode,
        "channels": int(channels),
        "head_bone": head_bone if bone_path_active else None,
        "rest_displacement_m": rest,
        "refused_rest_displacement_m": refused,
        "skip_reason": skip_reason,
    }


class HeartbeatSender:
    """Cadence-capped, best-effort heartbeat sender. Never raises.

    ``maybe_send`` sends at most ~2 Hz and swallows socket failures: the
    first failure of a streak is logged once, later consecutive failures
    are only counted, and a failure never propagates into the consumer
    loop. A failed attempt counts against the cadence too, so a dead link
    retries at ~2 Hz instead of spinning on every tick.
    """

    def __init__(self, revision: int = 0, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_attempt: float | None = None
        self._failing = False
        self.revision = revision
        self.send_failures = 0

    def bump_revision(self) -> None:
        """Increment the bind revision (the consumer calls it on rebind)."""
        self.revision += 1

    def maybe_send(self, sock, addr, bind: dict | None) -> bool:  # noqa: ANN001 - socket.socket
        """Send one heartbeat if the cadence cap allows. True when sent.

        ``addr`` is the sender address ``recvfrom`` returned; None means
        nothing has arrived yet and there is nobody to answer.
        """
        if addr is None:
            return False
        now = self._clock()
        if self._last_attempt is not None and (now - self._last_attempt) < MIN_SEND_INTERVAL_S:
            return False
        self._last_attempt = now
        return self._send(sock, addr, bind)

    def _send(self, sock, addr, bind) -> bool:  # noqa: ANN001 - socket.socket
        data = build_heartbeat(bind, int(time.time() * 1000.0), self.revision)
        try:
            sock.sendto(data, addr)
        except OSError as exc:
            self.send_failures += 1
            if not self._failing:
                logger.warning(
                    "heartbeat send failed (further consecutive failures are silent): %s", exc
                )
                self._failing = True
            return False
        if self._failing:
            logger.info("heartbeat send recovered after %d failures", self.send_failures)
            self._failing = False
        return True

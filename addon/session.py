"""Session record/replay for RealCapture packet streams (pure logic, no bpy).

File format (JSONL, one JSON object per line):
- First line:  ``{"v": 1, "kind": "realcapture-session"}``
- Data lines:  ``{"recv_t": <epoch ms int>, "packet": {<schema packet dict>}}``

``recv_t`` is the addon-side arrival time (epoch ms), so replay reproduces the
original end-to-end timing including transport jitter. Data lines are
validated with the packet schema; malformed lines are skipped and counted.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import Packet, PacketValidationError, validate_packet_dict

SESSION_FORMAT_VERSION = 1
SESSION_HEADER_KIND = "realcapture-session"


class SessionError(ValueError):
    """Raised for structurally invalid session files."""


class SessionRecorder:
    """Writes packet streams to a JSONL file. One session per file."""

    def __init__(self, path: str | Path, flush_every: int = 60) -> None:
        self._path = Path(path)
        if flush_every < 1:
            raise ValueError("flush_every must be >= 1")
        self._flush_every = flush_every
        self._file = None
        self.packets_recorded = 0

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    @property
    def path(self) -> Path:
        return self._path

    def start(self) -> None:
        if self._file is not None:
            raise RuntimeError("recorder already running")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", encoding="utf-8", newline="\n")
        self._file.write(
            json.dumps({"v": SESSION_FORMAT_VERSION, "kind": SESSION_HEADER_KIND}) + "\n"
        )

    def record(self, packet: Packet, recv_epoch_ms: int) -> None:
        if self._file is None:
            raise RuntimeError("recorder not started")
        line = json.dumps({"recv_t": recv_epoch_ms, "packet": packet.to_dict()})
        self._file.write(line + "\n")
        self.packets_recorded += 1
        if self.packets_recorded % self._flush_every == 0:
            self._file.flush()

    def stop(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def read_session(path: str | Path) -> tuple[list[tuple[int, Packet]], int]:
    """Load a session file.

    Returns ``(entries, skipped)`` where entries are ``(recv_epoch_ms, Packet)``
    in file order and ``skipped`` counts malformed data lines. Raises
    SessionError when the file is not a RealCapture session.
    """
    entries: list[tuple[int, Packet]] = []
    skipped = 0
    saw_header = False

    with Path(path).open("r", encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue

            if obj.get("kind") == SESSION_HEADER_KIND:
                if obj.get("v") != SESSION_FORMAT_VERSION:
                    raise SessionError(
                        f"unsupported session format version: {obj.get('v')!r}"
                    )
                saw_header = True
                continue

            try:
                recv_t = obj["recv_t"]
                packet_dict = obj["packet"]
                if not isinstance(recv_t, int) or isinstance(recv_t, bool):
                    raise ValueError("recv_t must be an integer")
                validated = validate_packet_dict(packet_dict)
            except (KeyError, TypeError, ValueError):
                skipped += 1
                continue

            entries.append(
                (
                    recv_t,
                    Packet(
                        t=validated["t"],
                        engine=validated["engine"],
                        conf=validated["conf"],
                        pose=dict(validated["pose"]),
                        shapes=dict(validated["shapes"]),
                        extra=dict(validated.get("extra", {})),
                    ),
                )
            )

    if not saw_header:
        raise SessionError(f"missing RealCapture session header in {path}")
    return entries, skipped


class ReplayScheduler:
    """Replays session entries preserving original inter-arrival timing."""

    def __init__(self, entries: list[tuple[int, Packet]]) -> None:
        if not entries:
            raise ValueError("cannot replay an empty session")
        self._entries = sorted(entries, key=lambda item: item[0])
        self._index = 0
        self._start_ms: float | None = None

    @property
    def duration_ms(self) -> int:
        first = self._entries[0][0]
        last = self._entries[-1][0]
        return max(0, last - first)

    def start(self, now_monotonic_ms: float) -> None:
        self._start_ms = now_monotonic_ms
        self._index = 0

    def poll(self, now_monotonic_ms: float) -> list[Packet]:
        """Return every entry whose original time has elapsed by now."""
        if self._start_ms is None:
            raise RuntimeError("scheduler not started")
        elapsed = now_monotonic_ms - self._start_ms
        due: list[Packet] = []
        while self._index < len(self._entries):
            recv_t, packet = self._entries[self._index]
            if recv_t - self._entries[0][0] <= elapsed:
                due.append(packet)
                self._index += 1
            else:
                break
        return due

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._entries)

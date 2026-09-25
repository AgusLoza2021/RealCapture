"""Companion dashboard hub: pure state aggregation for the web dashboard.

This module is deliberately free of web frameworks and bpy: it aggregates
capture-side facts into a JSON-ready snapshot and broadcasts snapshots to
subscribers (the WebSocket layer in work unit U2).

Channel activity rule (deterministic): each shape channel keeps its latest
value plus an activity meter that decays geometrically with a 1.0 s half-life
against the injected monotonic clock:

    activity = max(|value|, activity * 0.5 ** (dt / 1.0))

Top-N channels are ordered by activity descending, ties broken by channel
name ascending.

Send rate (fps) is computed over a sliding 5 s window of send timestamps.

Thread model: the capture thread calls the record_* mutators; the web server
thread calls snapshot() / subscribe() / publish(). All mutable state is
guarded by a single re-entrant lock.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"

#: Half-life, in seconds, of the channel activity decay.
ACTIVITY_HALF_LIFE_S = 1.0

#: Sliding window, in seconds, used to compute the send rate.
RATE_WINDOW_S = 5.0

#: Default ring buffer capacity for rate/processing-time samples.
DEFAULT_BUFFER_CAPACITY = 300

#: Default number of channels returned in a snapshot.
DEFAULT_TOP_CHANNELS = 12


def _default_clock() -> float:
    import time

    return time.monotonic()


class DashboardHub:
    """Aggregates capture facts into JSON-ready snapshots and broadcasts them."""

    def __init__(
        self,
        buffer_capacity: int = DEFAULT_BUFFER_CAPACITY,
        clock: Callable[[], float] = _default_clock,
    ) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._created_s = clock()
        self._status = STATUS_IDLE
        self._engine = ""
        self._udp_host = ""
        self._udp_port = 0
        self._packets_sent = 0
        self._send_errors = 0
        self._record_active = False
        self._record_path: Optional[str] = None
        self._send_times: deque = deque(maxlen=int(RATE_WINDOW_S * 240))
        self._proc_ms: deque = deque(maxlen=buffer_capacity)
        self._last_packet: Optional[Dict[str, Any]] = None
        self._channel_value: Dict[str, float] = {}
        self._channel_activity: Dict[str, float] = {}
        self._last_activity_s = self._created_s

    # -- capture lifecycle ------------------------------------------------------

    def begin_capture(self, engine: str, udp_host: str, udp_port: int) -> None:
        """Mark capture as running and reset per-session counters."""
        with self._lock:
            self._status = STATUS_RUNNING
            self._engine = engine
            self._udp_host = udp_host
            self._udp_port = udp_port
            self._packets_sent = 0
            self._send_errors = 0
            self._send_times.clear()
            self._proc_ms.clear()
            self._last_packet = None
            self._channel_value.clear()
            self._channel_activity.clear()
            self._last_activity_s = self._clock()

    def end_capture(self) -> None:
        """Mark capture as stopped (counters are kept for the final report)."""
        with self._lock:
            self._status = STATUS_STOPPED

    def set_record(self, active: bool, path: Optional[str] = None) -> None:
        with self._lock:
            self._record_active = active
            self._record_path = path if active else None

    # -- per-packet facts -------------------------------------------------------

    def record_sent(
        self,
        shapes: Dict[str, float],
        conf: float,
        packet_t: int,
        proc_ms: float,
        now: Optional[float] = None,
    ) -> None:
        """Record one successfully sent packet (capture thread only)."""
        now_s = self._clock() if now is None else now
        with self._lock:
            self._packets_sent += 1
            self._send_times.append(now_s)
            self._proc_ms.append(float(proc_ms))
            self._last_packet = {"t": int(packet_t), "conf": float(conf), "sent_s": now_s}
            self._update_channels(shapes, now_s)

    def record_send_error(self) -> None:
        with self._lock:
            self._send_errors += 1

    def _update_channels(self, shapes: Dict[str, float], now_s: float) -> None:
        dt = max(0.0, now_s - self._last_activity_s)
        decay = 0.5 ** (dt / ACTIVITY_HALF_LIFE_S)
        for name, value in shapes.items():
            previous = self._channel_activity.get(name, 0.0)
            self._channel_activity[name] = max(abs(float(value)), previous * decay)
            self._channel_value[name] = float(value)
        self._last_activity_s = now_s

    # -- snapshots --------------------------------------------------------------

    def send_rate(self, now: Optional[float] = None) -> float:
        """Packets per second over the sliding window (0.0 when unknown)."""
        now_s = self._clock() if now is None else now
        with self._lock:
            window = [t for t in self._send_times if now_s - t <= RATE_WINDOW_S]
            if len(window) < 2:
                return 0.0
            span = now_s - window[0]
            if span <= 0.0:
                return 0.0
            return (len(window) - 1) / span

    def top_channels(self, limit: int = DEFAULT_TOP_CHANNELS) -> List[Dict[str, Any]]:
        """Channels ordered by activity desc, name asc (deterministic)."""
        with self._lock:
            items = [
                {"name": name, "value": self._channel_value[name], "activity": activity}
                for name, activity in self._channel_activity.items()
            ]
        items.sort(key=lambda item: (-item["activity"], item["name"]))
        return items[:limit]

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Consistent, JSON-serializable view of the current state."""
        now_s = self._clock() if now is None else now
        with self._lock:
            proc = sorted(self._proc_ms)
            fps = self._fps_locked(now_s)
            last = None
            if self._last_packet is not None:
                last = {
                    "t": self._last_packet["t"],
                    "conf": self._last_packet["conf"],
                    "age_s": max(0.0, now_s - self._last_packet["sent_s"]),
                }
            return {
                "status": self._status,
                "engine": self._engine,
                "udp": {"host": self._udp_host, "port": self._udp_port},
                "packets_sent": self._packets_sent,
                "send_errors": self._send_errors,
                "fps": fps,
                "proc_ms_avg": sum(proc) / len(proc) if proc else 0.0,
                "proc_ms_max": proc[-1] if proc else 0.0,
                "uptime_s": max(0.0, now_s - self._created_s),
                "last_packet": last,
                "record": {"active": self._record_active, "path": self._record_path},
                "fps_history": list(self._fps_samples_locked()),
                "proc_ms_history": list(self._proc_ms),
                "channels": self.top_channels(),
            }

    def _fps_locked(self, now_s: float) -> float:
        window = [t for t in self._send_times if now_s - t <= RATE_WINDOW_S]
        if len(window) < 2:
            return 0.0
        span = now_s - window[0]
        if span <= 0.0:
            return 0.0
        return (len(window) - 1) / span

    def _fps_samples_locked(self) -> List[float]:
        """Per-interval instant rate, one sample per consecutive send pair."""
        times = list(self._send_times)
        samples: List[float] = []
        for previous, current in zip(times, times[1:]):
            dt = current - previous
            samples.append(1.0 / dt if dt > 0.0 else 0.0)
        return samples



class BroadcastHub:
    """Thread-safe publish/subscribe of dashboard snapshots.

    Subscribers are plain callables receiving one snapshot dict. publish()
    never blocks and never fails because of a subscriber: exceptions raised
    by a subscriber are swallowed after being reported to the error hook.
    """

    def __init__(self, on_subscriber_error: Optional[Callable[[BaseException], None]] = None) -> None:
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []
        self._on_error = on_subscriber_error

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        """Add a subscriber; returns an idempotent unsubscribe callable."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
            entry = callback

        def unsubscribe() -> None:
            self.unsubscribe(entry)

        return unsubscribe

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def publish(self, snapshot: Dict[str, Any]) -> None:
        with self._lock:
            targets = tuple(self._subscribers)
        for target in targets:
            try:
                target(snapshot)
            except Exception as exc:  # noqa: BLE001 - one bad subscriber must not stall the loop
                if self._on_error is not None:
                    self._on_error(exc)

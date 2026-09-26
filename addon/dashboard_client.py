"""Pure dashboard reader for the Blender-native plugin: probe the dashboard
port and poll ``GET /api/status`` on a daemon thread.

No bpy imports here on purpose: this module runs under pytest on a Python
without Blender, and the UI unit (P4) is the only bpy-side caller.

Rules this module enforces (frozen contract, odd/tasks/blender-native-plugin.md
P3):

- The dashboard is the single source of truth for the lights. This module
  computes NO threshold and NEVER rewrites, renames or reorders what the
  dashboard sends: ``parse_status`` returns the ``connections`` array
  verbatim, an empty array being a legitimate answer.
- No network I/O on Blender's main thread (the poller's fetch runs on a
  daemon thread with a timeout); ``snapshot()`` only reads a cached value
  under a lock and can never freeze the UI.
- Absence is never green: on a failed read the snapshot keeps the LAST GOOD
  ``fetched_at`` (monotonic clock) and carries the reason, so the UI can
  label the data with its age instead of presenting it as live. A failed
  read never sets ``fetched_at``.
- The probe is the tri-state the launcher needs: free / dashboard / stranger,
  and it never raises for a normal network refusal.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .backend_process import (
    PROBE_DASHBOARD,
    PROBE_FREE,
    PROBE_STRANGER,
    ProbeResult,
)

#: The one path this module knows how to read.
DASHBOARD_STATUS_PATH = "/api/status"


class StatusError(ValueError):
    """Refusal while reading or parsing the dashboard status."""


def status_url(dashboard_port: int, *, host: str = "127.0.0.1") -> str:
    """The status URL for a dashboard port."""
    return f"http://{host}:{dashboard_port}{DASHBOARD_STATUS_PATH}"


def parse_status(payload: Any) -> tuple[dict, ...]:
    """Return the ``connections`` array verbatim, as a tuple of the same dicts.

    Raises :class:`StatusError` when ``connections`` is missing or is not a
    list. Nothing is added, renamed, reordered or filtered.
    """
    if not isinstance(payload, dict):
        raise StatusError("dashboard status is not a JSON object")
    if "connections" not in payload:
        raise StatusError("dashboard status has no 'connections' key")
    connections = payload["connections"]
    if not isinstance(connections, list):
        raise StatusError(
            f"dashboard 'connections' is not a list (got {type(connections).__name__})"
        )
    return tuple(connections)


def format_age(age_s: float) -> str:
    """Human label for a snapshot age: ``0.4 s``, ``12 s``, ``3 min``."""
    if age_s < 0:
        age_s = 0.0
    if age_s < 10:
        return f"{age_s:.1f} s"
    if age_s < 60:
        return f"{int(age_s)} s"
    return f"{int(age_s // 60)} min"


def _read_json_response(raw: bytes, url: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise StatusError(f"{url} answered non-JSON: {exc}") from exc


def probe_dashboard(
    dashboard_port: int,
    *,
    timeout_s: float = 0.5,
    host: str = "127.0.0.1",
) -> ProbeResult:
    """Tri-state probe of the dashboard port; never raises for a network refusal.

    - Nothing answers: ``PROBE_FREE``.
    - ``GET /api/status`` answers JSON with a ``connections`` key:
      ``PROBE_DASHBOARD``.
    - Something answers but not like this dashboard (HTTP error status,
      non-JSON, JSON without ``connections``): ``PROBE_STRANGER`` naming what
      answered.
    """
    url = status_url(dashboard_port, host=host)
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status = getattr(response, "status", None) or response.getcode()
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return ProbeResult(
            PROBE_STRANGER, f"{url} answered HTTP {exc.code} (not this dashboard)"
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return ProbeResult(PROBE_FREE, f"nothing answers on port {dashboard_port} ({reason})")
    try:
        payload = _read_json_response(raw, url)
    except StatusError as exc:
        return ProbeResult(
            PROBE_STRANGER, f"{exc} (HTTP {status}; not this dashboard)"
        )
    if isinstance(payload, dict) and "connections" in payload:
        count = len(payload["connections"]) if isinstance(payload["connections"], list) else -1
        return ProbeResult(PROBE_DASHBOARD, f"dashboard answering at {url} ({count} connections)")
    return ProbeResult(
        PROBE_STRANGER,
        f"{url} answered JSON without a 'connections' key (HTTP {status}; not this dashboard)",
    )


def fetch_status(
    dashboard_port: int,
    *,
    timeout_s: float = 1.5,
    host: str = "127.0.0.1",
    opener: Any = None,
) -> dict:
    """Fetch and return the raw status object; raises :class:`StatusError` on failure.

    ``opener`` is injectable for deterministic tests; it defaults to a fresh
    :class:`urllib.request.OpenerDirector`.
    """
    url = status_url(dashboard_port, host=host)
    director = opener if opener is not None else urllib.request.build_opener()
    try:
        with director.open(url, timeout=timeout_s) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise StatusError(f"HTTP {exc.code}") from exc
    except TimeoutError as exc:
        raise StatusError(f"timeout after {timeout_s} s") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            raise StatusError(f"timeout after {timeout_s} s") from exc
        if isinstance(reason, ConnectionRefusedError):
            raise StatusError("connection refused") from exc
        raise StatusError(str(reason)) from exc
    except OSError as exc:
        raise StatusError(str(exc)) from exc
    payload = _read_json_response(raw, url)
    if not isinstance(payload, dict):
        raise StatusError("dashboard status is not a JSON object")
    return payload


@dataclass(frozen=True)
class Snapshot:
    """The last cached view of the dashboard; reading it does no I/O.

    ``connections`` is the last good array verbatim (``()`` if there was never
    a good read); ``fetched_at`` is the monotonic time of the last SUCCESSFUL
    read (``0.0`` if never); ``error`` is ``None`` when the last read
    succeeded, else the reason. Absence is never presented as live data.
    """

    connections: tuple[dict, ...]
    fetched_at: float
    error: Optional[str]


class DashboardPoller:
    """Polls the dashboard on a daemon thread; the UI only reads snapshots."""

    def __init__(
        self,
        dashboard_port: int,
        *,
        host: str = "127.0.0.1",
        interval_s: float = 0.5,
        timeout_s: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
        fetcher: Optional[Callable[[], dict]] = None,
    ) -> None:
        self._port = dashboard_port
        self._host = host
        self._interval_s = interval_s
        self._timeout_s = timeout_s
        self._clock = clock
        if fetcher is not None:
            self._fetcher = fetcher
        else:
            def default_fetcher() -> dict:
                return fetch_status(
                    self._port, timeout_s=self._timeout_s, host=self._host
                )

            self._fetcher = default_fetcher
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._connections: tuple[dict, ...] = ()
        self._fetched_at = 0.0
        self._error: Optional[str] = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._wake.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="realcapture-dashboard-poll",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                payload = self._fetcher()
                connections = parse_status(payload)
            except Exception as exc:  # noqa: BLE001 - a failed read is a snapshot state, not a crash
                with self._lock:
                    self._error = str(exc) or type(exc).__name__
            else:
                with self._lock:
                    self._connections = connections
                    self._fetched_at = self._clock()
                    self._error = None
            if self._wake.wait(self._interval_s):
                break

    def stop(self, *, timeout_s: float = 2.0) -> None:
        """Wake the thread and wait for it to exit; safe to call twice and
        safe to call when never started."""
        self._wake.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_s)
            if not thread.is_alive():
                self._thread = None

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def snapshot(self) -> Snapshot:
        """The cached view; no I/O, no blocking."""
        with self._lock:
            return Snapshot(
                connections=self._connections,
                fetched_at=self._fetched_at,
                error=self._error,
            )

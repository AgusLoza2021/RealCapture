"""Unit tests for the pure dashboard reader (no bpy, a real local HTTP server).

Gates, not decoration: the parse is verbatim, the probe is the real tri-state
against real sockets, and the poller proves that snapshot() never does I/O on
the caller's thread, that a failed read keeps the last good data labelled by
its age, and that stop() leaves no live thread.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from addon.backend_process import (
    PROBE_DASHBOARD,
    PROBE_FREE,
    PROBE_STRANGER,
    ProbeResult,
)
from addon.dashboard_client import (
    DASHBOARD_STATUS_PATH,
    DashboardPoller,
    Snapshot,
    StatusError,
    fetch_status,
    format_age,
    parse_status,
    probe_dashboard,
    status_url,
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOpener:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.calls: list[tuple] = []

    def open(self, url, timeout=None):
        self.calls.append((url, timeout))
        return _FakeResponse(self._body)


class _RaisingOpener:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def open(self, url, timeout=None):
        raise self._exc


# ---------------------------------------------------------------------------
# url / parse / format


def test_status_url_uses_the_frozen_path():
    assert status_url(8765) == f"http://127.0.0.1:8765{DASHBOARD_STATUS_PATH}"
    assert status_url(8765, host="0.0.0.0") == f"http://0.0.0.0:8765{DASHBOARD_STATUS_PATH}"


def test_parse_status_returns_connections_verbatim():
    first = {"id": "a", "label": "webcam", "state": "ok", "reason": "r", "detail": "d"}
    second = {"id": "b", "label": "blender", "state": "stale", "reason": "r2", "detail": ""}
    payload = {"connections": [first, second], "other": "untouched"}
    result = parse_status(payload)
    assert isinstance(result, tuple)
    assert result == (first, second)
    assert result[0] is first  # the SAME dicts, in the SAME order


def test_parse_status_empty_array_is_legitimate():
    assert parse_status({"connections": []}) == ()


def test_parse_status_refuses_missing_key():
    with pytest.raises(StatusError):
        parse_status({"nope": []})


@pytest.mark.parametrize("bad", ["not-a-list", {"connections": 1}, 42, None])
def test_parse_status_refuses_non_list_connections(bad):
    with pytest.raises(StatusError):
        parse_status(bad)


def test_parse_status_refuses_non_dict_payload():
    with pytest.raises(StatusError):
        parse_status([{"connections": []}])


@pytest.mark.parametrize(
    "age_s, expected",
    [(0.0, "0.0 s"), (0.4, "0.4 s"), (9.96, "10.0 s"), (12, "12 s"), (59, "59 s"), (180, "3 min"), (125.0, "2 min")],
)
def test_format_age(age_s, expected):
    assert format_age(age_s) == expected


# ---------------------------------------------------------------------------
# fetch_status (injected openers, deterministic)


def test_fetch_status_returns_the_object():
    payload = {"connections": [{"id": "a"}]}
    opener = _FakeOpener(json.dumps(payload).encode("utf-8"))
    assert fetch_status(8765, opener=opener) == payload
    url, timeout = opener.calls[0]
    assert url == status_url(8765)
    assert timeout == pytest.approx(1.5)


def test_fetch_status_http_error_names_the_code():
    exc = urllib.error.HTTPError(status_url(8765), 404, "gone", {}, None)
    with pytest.raises(StatusError) as excinfo:
        fetch_status(8765, opener=_RaisingOpener(exc))
    assert "HTTP 404" in str(excinfo.value)


def test_fetch_status_connection_refused():
    exc = urllib.error.URLError(ConnectionRefusedError(10061))
    with pytest.raises(StatusError) as excinfo:
        fetch_status(8765, opener=_RaisingOpener(exc))
    assert "connection refused" in str(excinfo.value)


def test_fetch_status_timeout_names_the_budget():
    exc = urllib.error.URLError(TimeoutError("timed out"))
    with pytest.raises(StatusError) as excinfo:
        fetch_status(8765, timeout_s=1.5, opener=_RaisingOpener(exc))
    assert "timeout after 1.5 s" in str(excinfo.value)


def test_fetch_status_non_json():
    with pytest.raises(StatusError):
        fetch_status(8765, opener=_FakeOpener(b"<html>hi</html>"))


# ---------------------------------------------------------------------------
# probe_dashboard: REAL local http.server on an ephemeral port


class _Handler(BaseHTTPRequestHandler):
    response_body: bytes = b'{"connections": []}'
    response_status: int = 200

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path != DASHBOARD_STATUS_PATH:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, *args):  # keep the test output quiet
        pass


class _Server:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5.0)
        return False


def _closed_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_probe_dashboard_answers_like_the_dashboard():
    with _Server() as srv:
        result = probe_dashboard(srv.port, timeout_s=2.0)
    assert result.state == PROBE_DASHBOARD
    assert "connections" in result.detail


def test_probe_dashboard_plain_text_is_a_stranger():
    _Handler.response_body = b"hello, not json"
    try:
        with _Server() as srv:
            result = probe_dashboard(srv.port, timeout_s=2.0)
    finally:
        _Handler.response_body = b'{"connections": []}'
    assert result.state == PROBE_STRANGER
    assert "non-JSON" in result.detail


def test_probe_dashboard_404_is_a_stranger():
    _Handler.response_status = 404
    try:
        with _Server() as srv:
            result = probe_dashboard(srv.port, timeout_s=2.0)
    finally:
        _Handler.response_status = 200
    assert result.state == PROBE_STRANGER
    assert "HTTP 404" in result.detail


def test_probe_dashboard_json_without_connections_is_a_stranger():
    _Handler.response_body = b'{"lights": []}'
    try:
        with _Server() as srv:
            result = probe_dashboard(srv.port, timeout_s=2.0)
    finally:
        _Handler.response_body = b'{"connections": []}'
    assert result.state == PROBE_STRANGER
    assert "connections" in result.detail


def test_probe_dashboard_closed_port_is_free():
    port = _closed_port()
    result = probe_dashboard(port, timeout_s=2.0)
    assert result.state == PROBE_FREE


# ---------------------------------------------------------------------------
# DashboardPoller: real server, real threads


def _wait_for(predicate, timeout_s: float = 5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_poller_caches_good_reads_and_labels_failures_with_age():
    with _Server() as srv:
        poller = DashboardPoller(srv.port, interval_s=0.05, timeout_s=2.0)
        try:
            poller.start()
            assert _wait_for(
                lambda: poller.snapshot().error is None
                and poller.snapshot().fetched_at > 0.0
            )
            good = poller.snapshot()
            assert good.connections == ()  # the real array, verbatim (empty)
            assert good.error is None

            # The server disappears; the next read fails.
            srv.server.shutdown()
            srv.server.server_close()
            assert _wait_for(lambda: poller.snapshot().error is not None)
            bad = poller.snapshot()
            assert bad.error is not None
            assert bad.fetched_at == good.fetched_at  # last GOOD read, unchanged
            assert bad.connections == ()  # last good data is retained, age-labelled
        finally:
            poller.stop()


def test_poller_snapshot_does_no_io_on_caller_thread():
    fetcher_started = threading.Event()
    release = threading.Event()

    def blocked_fetcher():
        fetcher_started.set()
        release.wait(timeout=10.0)
        return {"connections": []}

    poller = DashboardPoller(8765, fetcher=blocked_fetcher, interval_s=0.05)
    try:
        poller.start()
        assert fetcher_started.wait(timeout=5.0)
        started = time.monotonic()
        snap = poller.snapshot()  # must not block on the stuck fetcher
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        assert isinstance(snap, Snapshot)
        assert snap.fetched_at == 0.0  # no successful read yet
        assert snap.connections == ()
    finally:
        release.set()
        poller.stop()


def test_poller_stop_leaves_no_live_thread_and_is_idempotent():
    poller = DashboardPoller(8765, fetcher=lambda: {"connections": []})
    poller.stop()  # never started: no raise
    poller.start()
    assert poller.is_alive() is True
    poller.stop()
    poller.stop()  # twice: no raise
    assert poller.is_alive() is False
    assert not any(
        thread.name == "realcapture-dashboard-poll"
        for thread in threading.enumerate()
    )


def test_poller_start_twice_keeps_one_thread():
    poller = DashboardPoller(8765, fetcher=lambda: {"connections": []}, interval_s=0.05)
    try:
        poller.start()
        first = poller._thread
        poller.start()
        assert poller._thread is first
        assert _wait_for(lambda: poller.snapshot().error is None)
    finally:
        poller.stop()


def test_poller_failed_read_error_carries_reason():
    def refused():
        raise StatusError("connection refused")

    poller = DashboardPoller(8765, fetcher=refused, interval_s=0.05)
    try:
        poller.start()
        assert _wait_for(lambda: poller.snapshot().error is not None)
        snap = poller.snapshot()
        assert snap.error == "connection refused"
        assert snap.fetched_at == 0.0  # a failed read never sets fetched_at
    finally:
        poller.stop()


def test_probe_result_shape_is_shared_with_backend_process():
    assert ProbeResult(PROBE_FREE).state == PROBE_FREE
    assert ProbeResult(PROBE_FREE).detail == ""
    assert PROBE_DASHBOARD == "dashboard" and PROBE_STRANGER == "stranger"

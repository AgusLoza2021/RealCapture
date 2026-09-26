"""Companion dashboard HTTP/WebSocket server (FastAPI).

Serves the static dashboard, a JSON status endpoint, record/stop controls, and
a WebSocket that pushes hub snapshots as they are published. Runs inside the
capture-backend process (threads are fine here; bpy is never touched).

Standalone smoke run (idle hub, no capture):

    python -m backend.dashboard.server --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from starlette.responses import PlainTextResponse, StreamingResponse

from .frametap import FrameTap, clamp_stream_fps, should_encode
from .hub import BroadcastHub, DashboardHub

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Interval, in seconds, between WebSocket keep-alive pings when idle.
WS_IDLE_PING_S = 5.0

#: Poll interval, in seconds, for the MJPEG stream when the encode gate says wait.
STREAM_POLL_S = 0.02

#: Seconds a stream may keep running without a fresh frame from the tap before
#: it ends. Re-looping a stale frame forever would look healthy while the
#: camera is gone — that is exactly the silence this project refuses to show.
STREAM_IDLE_TIMEOUT_S = 5.0

#: Boundary token used between multipart parts of the MJPEG stream.
MJPEG_BOUNDARY = "frame"


def build_jpeg_encoder(target_width: int = 640, quality: int = 80) -> Callable[[Any], bytes]:
    """Return a callable that encodes a raw BGR frame to JPEG bytes.

    Frames are downscaled to ``target_width`` px wide (aspect kept) before
    encoding: the full camera frame is far too heavy for the stream rate.
    cv2 is imported lazily inside the closure so importing this module never
    requires OpenCV (the test environment has no cv2).
    """

    def encode(frame: Any) -> bytes:
        import cv2

        height, width = frame.shape[:2]
        if width > target_width:
            scale = target_width / float(width)
            frame = cv2.resize(frame, (target_width, max(1, int(height * scale))))
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return buf.tobytes()

    return encode


class SnapshotBridge:
    """Bridges thread-side BroadcastHub publishes into asyncio waiters."""

    def __init__(self, broadcast: BroadcastHub) -> None:
        self._latest: Optional[Dict[str, Any]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._event: Optional[asyncio.Event] = None
        self._lock = threading.Lock()
        self._unsubscribe = broadcast.subscribe(self._on_snapshot)

    def _on_snapshot(self, snapshot: Dict[str, Any]) -> None:
        with self._lock:
            self._latest = snapshot
            loop, event = self._loop, self._event
        if loop is not None and event is not None:
            loop.call_soon_threadsafe(event.set)

    def bind(self, loop: asyncio.AbstractEventLoop, event: asyncio.Event) -> None:
        with self._lock:
            self._loop = loop
            self._event = event

    async def next_snapshot(self, timeout: float = WS_IDLE_PING_S) -> Optional[Dict[str, Any]]:
        """Return the newest snapshot, waiting up to timeout for a fresh one."""
        assert self._event is not None
        self._event.clear()
        with self._lock:
            snapshot = self._latest
        if snapshot is not None:
            self._latest = None
            return snapshot
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        with self._lock:
            snapshot, self._latest = self._latest, None
        return snapshot

    def close(self) -> None:
        self._unsubscribe()


class DashboardControls:
    """Capture-control surface wired by the embedding process (run_capture)."""

    def __init__(
        self,
        stop_capture: Optional[Callable[[], None]] = None,
        set_record: Optional[Callable[[bool, Optional[str]], None]] = None,
    ) -> None:
        self._stop_capture = stop_capture
        self._set_record = set_record

    def stop_capture(self) -> None:
        if self._stop_capture is None:
            raise PermissionError("capture control is not available in this mode")
        self._stop_capture()

    def set_record(self, active: bool, path: Optional[str] = None) -> None:
        if self._set_record is None:
            raise PermissionError("record control is not available in this mode")
        self._set_record(active, path)


def create_app(
    hub: DashboardHub,
    broadcast: Optional[BroadcastHub] = None,
    controls: Optional[DashboardControls] = None,
    frame_tap: Optional[FrameTap] = None,
    stream_fps: float = 12.0,
    stream_idle_timeout_s: float = STREAM_IDLE_TIMEOUT_S,
) -> Any:
    """Build the FastAPI dashboard application.

    ``frame_tap`` is optional: without it the dashboard stays telemetry-only
    and the camera endpoint answers 503 instead of pretending to stream.
    """
    broadcast = broadcast or BroadcastHub()
    controls = controls or DashboardControls()
    app = FastAPI(title="RealCapture Dashboard", docs_url=None, redoc_url=None)
    bridge = SnapshotBridge(broadcast)
    min_encode_interval_s = 1.0 / clamp_stream_fps(stream_fps)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="dashboard UI not built yet")
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    @app.get("/api/status")
    async def status() -> Dict[str, Any]:
        return hub.snapshot()

    @app.post("/api/record")
    async def record(body: Dict[str, Any]) -> Dict[str, Any]:
        active = bool(body.get("active", False))
        path = body.get("path")
        try:
            controls.set_record(active, path if active else None)
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "record": {"active": active, "path": path if active else None}}

    @app.post("/api/capture/stop")
    async def stop() -> Dict[str, Any]:
        try:
            controls.stop_capture()
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "status": "stopping"}

    async def _mjpeg_parts(tap: FrameTap) -> Any:
        """Yield MJPEG parts while the encode gate allows; owns one subscription.

        The consumer is registered on entry and unregistered in a ``finally``
        so a disconnected browser can never leave a phantom subscriber (this
        runs both on client disconnect and on normal stream end). When the
        gate disallows, it sleeps briefly instead of busy-looping. The stream
        ends when no fresh frame arrives within ``stream_idle_timeout_s``:
        a stopped capture loop must not keep re-looping a stale frame.
        """
        unsubscribe = tap.subscribe()
        last_encode_t: Optional[float] = None
        last_seen_frame_t: Optional[float] = None
        frame_seen_t = 0.0
        try:
            while True:
                now = time.monotonic()
                current = tap.peek()
                if current is None:
                    await asyncio.sleep(STREAM_POLL_S)
                    continue
                frame, frame_t = current
                if frame_t != last_seen_frame_t:
                    last_seen_frame_t = frame_t
                    frame_seen_t = now
                elif now - frame_seen_t > stream_idle_timeout_s:
                    return  # capture stopped producing frames; end honestly
                if should_encode(now, last_encode_t, tap.subscriber_count, min_encode_interval_s):
                    data = tap.encode_frame(frame)
                    if data:
                        last_encode_t = now
                        yield (
                            f"--{MJPEG_BOUNDARY}\r\n"
                            "Content-Type: image/jpeg\r\n"
                            f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
                            + data
                            + b"\r\n"
                        )
                await asyncio.sleep(STREAM_POLL_S)
        finally:
            unsubscribe()

    @app.get("/camera.mjpg")
    async def camera_mjpg() -> Any:
        """Stream the camera preview as multipart/x-mixed-replace MJPEG.

        Honesty rule: when the tap is unbound or no frame has arrived yet,
        answer 503 with a plain-text reason naming the missing thing instead
        of starting a stream that silently hangs looking healthy.
        """
        if frame_tap is None:
            return PlainTextResponse(
                "camera stream unavailable: no frame tap is bound "
                "(start capture with --dashboard to enable the preview)",
                status_code=503,
            )
        if frame_tap.peek() is None:
            return PlainTextResponse(
                "camera stream unavailable: no frame has arrived from the capture loop yet",
                status_code=503,
            )
        return StreamingResponse(
            _mjpeg_parts(frame_tap),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        )

    @app.get("/camera.jpg")
    async def camera_jpg() -> Any:
        """Return one JPEG snapshot of the newest camera frame.

        Deliberately does NOT consult the encode gate and does NOT subscribe:
        this is one explicit single-frame request from a human, not a stream,
        so the "idle means no encode" rule does not apply here. Honesty rule
        is the same as the stream: never fabricate a frame — 503 with a
        plain-text reason when the tap is unbound or no frame has arrived.
        ``Cache-Control: no-store`` keeps a stale snapshot from posing as live.
        """
        if frame_tap is None:
            return PlainTextResponse(
                "camera snapshot unavailable: no frame tap is bound "
                "(start capture with --dashboard to enable the preview)",
                status_code=503,
            )
        current = frame_tap.peek()
        if current is None:
            return PlainTextResponse(
                "camera snapshot unavailable: no frame has arrived from the capture loop yet",
                status_code=503,
            )
        data = frame_tap.encode_frame(current[0])
        if not data:
            return PlainTextResponse(
                "camera snapshot unavailable: no JPEG encoder is bound to the frame tap",
                status_code=503,
            )
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        event = asyncio.Event()
        bridge.bind(asyncio.get_running_loop(), event)
        try:
            await websocket.send_json(hub.snapshot())
            while True:
                snapshot = await bridge.next_snapshot()
                if snapshot is None:
                    await websocket.send_json({"kind": "ping"})
                    continue
                await websocket.send_json(snapshot)
        except WebSocketDisconnect:
            return
        finally:
            bridge.bind(None, None)  # type: ignore[arg-type]

    return app


def serve_standalone(port: int = 8765) -> None:  # pragma: no cover - manual smoke tool
    """Run the dashboard against an idle hub (development smoke test)."""
    import uvicorn

    hub = DashboardHub()
    app = create_app(hub)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":  # pragma: no cover - manual smoke tool
    parser = argparse.ArgumentParser(description="RealCapture dashboard (idle standalone mode)")
    parser.add_argument("--port", type=int, default=8765)
    serve_standalone(port=parser.parse_args().port)

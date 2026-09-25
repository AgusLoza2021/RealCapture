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
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from .hub import BroadcastHub, DashboardHub

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Interval, in seconds, between WebSocket keep-alive pings when idle.
WS_IDLE_PING_S = 5.0


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
) -> Any:
    """Build the FastAPI dashboard application."""
    broadcast = broadcast or BroadcastHub()
    controls = controls or DashboardControls()
    app = FastAPI(title="RealCapture Dashboard", docs_url=None, redoc_url=None)
    bridge = SnapshotBridge(broadcast)

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

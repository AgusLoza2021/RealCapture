"""RealCapture capture backend entry point.

Runs a capture engine as an external OS process and streams validated packets
to the Blender addon over UDP. Example:

    python backend/run_capture.py --engine mediapipe --camera 0 --port 11111
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import time
from pathlib import Path
from typing import Callable

# Bootstrap: allow running as a script (python backend/run_capture.py) while
# keeping package-relative imports intact.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.backends import (  # noqa: E402
    BackendImportError,
    CaptureBackend,
    MediaPipeBackend,
    OpenSeeFaceBackend,
)
from backend.backends.openseeface_backend import DEFAULT_OSF_PORT  # noqa: E402

logger = logging.getLogger("realcapture")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RealCapture facial capture backend")
    parser.add_argument("--engine", choices=["mediapipe", "openseeface"], default="mediapipe")
    parser.add_argument("--camera", type=int, default=0, help="camera index (0 = default webcam)")
    parser.add_argument("--fps", type=int, default=30, help="capture fps cap")
    parser.add_argument("--host", default="127.0.0.1", help="UDP host to send to")
    parser.add_argument("--port", type=int, default=11111, help="UDP port to send to")
    parser.add_argument(
        "--dashboard",
        type=int,
        default=0,
        metavar="PORT",
        help="serve the companion web dashboard on this port (e.g. 8765)",
    )
    parser.add_argument(
        "--stream-fps",
        type=float,
        default=12.0,
        help="camera preview stream fps for the dashboard (clamped to at most 15)",
    )
    parser.add_argument(
        "--osf-command",
        default="",
        help=(
            "openseeface only: tracker command, e.g. 'C:/OSF/Binary/facetracker.exe' "
            "or a quoted 'python C:/OSF/facetracker.py'"
        ),
    )
    parser.add_argument(
        "--osf-port",
        type=int,
        default=DEFAULT_OSF_PORT,
        help="openseeface only: local port the tracker streams to (backend listens here)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def build_backend(args: argparse.Namespace) -> CaptureBackend:
    kwargs = dict(
        camera_index=args.camera,
        fps=args.fps,
        udp_host=args.host,
        udp_port=args.port,
    )
    if args.engine == "mediapipe":
        return MediaPipeBackend(**kwargs)
    return OpenSeeFaceBackend(**kwargs, osf_command=args.osf_command, osf_port=args.osf_port)


def _tap_camera_age(tap) -> Callable[[], float | None]:  # noqa: ANN001 - FrameTap
    """Return a callable giving the age of the newest tapped frame, or None."""

    def camera_age_s() -> float | None:
        peeked = tap.peek()
        return None if peeked is None else time.monotonic() - peeked[1]

    return camera_age_s


class _HeartbeatSource:
    """Late-bound view of ``backend.heartbeat`` for the dashboard hub.

    The tracker exists only between start() and stop() and is replaced on
    every start, so the hub is handed a view that re-reads the attribute
    rather than a snapshot of it.
    """

    def __init__(self, backend: CaptureBackend) -> None:
        self._backend = backend

    def age_s(self, now: float) -> float | None:
        tracker = getattr(self._backend, "heartbeat", None)
        return None if tracker is None else tracker.age_s(now)

    def bind_report(self):  # noqa: ANN201 - tracker-owned payload
        tracker = getattr(self._backend, "heartbeat", None)
        return None if tracker is None else tracker.bind_report()


def _start_dashboard(backend: CaptureBackend, args: argparse.Namespace) -> threading.Thread:
    """Serve the companion dashboard in a daemon thread wired to this backend."""
    import socket as socket_mod

    import uvicorn

    from backend.dashboard.frametap import FrameTap, clamp_stream_fps
    from backend.dashboard.hub import BroadcastHub, DashboardHub
    from backend.dashboard.server import DashboardControls, build_jpeg_encoder, create_app

    broadcast = BroadcastHub(on_subscriber_error=lambda exc: logger.warning("dashboard subscriber failed: %s", exc))

    # Camera preview feed: the backend publishes raw BGR frames into the tap,
    # the dashboard encodes them at the capped rate when someone is watching.
    stream_fps = clamp_stream_fps(args.stream_fps)
    frame_tap = FrameTap(encode=build_jpeg_encoder())

    def on_frame(frame, frame_t: float) -> None:  # noqa: ANN001 - raw cv2 frame
        frame_tap.publish(frame, frame_t)

    backend.on_frame = on_frame

    # The status lights need each source's staleness; without the camera age
    # and the Blender heartbeat they can only report "unknown", which must
    # never be rendered as green.
    hub = DashboardHub(camera_age_s=_tap_camera_age(frame_tap), blender_source=_HeartbeatSource(backend))

    def on_packet(packet, proc_ms: float) -> None:  # noqa: ANN001 - schema.Packet
        hub.record_sent(
            shapes=packet.shapes,
            conf=packet.conf,
            packet_t=packet.t,
            proc_ms=proc_ms,
        )
        broadcast.publish(hub.snapshot())

    backend.on_packet = on_packet
    backend.on_send_error = hub.record_send_error
    hub.begin_capture(args.engine, args.host, args.port)

    def stop_capture() -> None:
        logger.info("dashboard requested capture stop")
        backend.stop()

    controls = DashboardControls(stop_capture=stop_capture)
    app = create_app(hub, broadcast, controls, frame_tap=frame_tap, stream_fps=stream_fps)
    config = uvicorn.Config(app, host="0.0.0.0", port=args.dashboard, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="dashboard-http", daemon=True)
    thread.start()

    lan_ip = "127.0.0.1"
    try:
        probe = socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        lan_ip = probe.getsockname()[0]
        probe.close()
    except OSError:
        pass
    print(f"Dashboard: http://{lan_ip}:{args.dashboard}  (same address from your phone)")
    return thread, hub


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        backend = build_backend(args)
    except BackendImportError as exc:
        logger.error("%s", exc)
        return 1

    sender_note = (
        f"engine={args.engine} camera={args.camera} fps={args.fps} "
        f"-> udp {args.host}:{args.port}"
    )
    print(f"RealCapture backend started: {sender_note}")

    start_time = time.monotonic()
    dashboard_hub = None
    if args.dashboard > 0:
        dashboard_thread, dashboard_hub = _start_dashboard(backend, args)
    exit_code = 0
    try:
        with backend:
            while backend.is_alive:
                time.sleep(0.5)
        # Thread finished on its own: that means the capture loop crashed
        # (KeyboardInterrupt while sleeping lands in the except below).
        exit_code = 1
    except KeyboardInterrupt:
        pass

    elapsed = time.monotonic() - start_time
    if dashboard_hub is not None:
        dashboard_hub.end_capture()
    avg_fps = backend.packets_sent / elapsed if elapsed > 0 else 0.0
    print(
        f"Stopped. packets={backend.packets_sent} "
        f"elapsed={elapsed:.1f}s avg_fps={avg_fps:.1f} send_errors={backend.send_errors}"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

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
    parser.add_argument("--visualize", action="store_true", help="show a live preview window")
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.visualize:
        logger.warning("--visualize is not implemented yet; running headless capture")

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
    avg_fps = backend.packets_sent / elapsed if elapsed > 0 else 0.0
    print(
        f"Stopped. packets={backend.packets_sent} "
        f"elapsed={elapsed:.1f}s avg_fps={avg_fps:.1f} send_errors={backend.send_errors}"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

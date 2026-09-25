"""Synthetic soak-test sender for RealCapture.

Streams realistic-looking synthetic packets (sine/cosine driven expression
channels and head pose) at a fixed rate so the Blender addon can be soak
tested for long sessions without a camera or a capture engine. Pair it with
the addon's Session Record to produce soak evidence (applied FPS stability,
memory behavior, transport latency).

Usage (from the backend venv or any Python 3.9+):

    python tools/soak_send.py --minutes 30 --hz 30 --port 11111 -v

Then enable the addon, Start Capture, and record the session file. On exit
the sender reports packets sent, send errors, and achieved rate vs target.
"""

from __future__ import annotations

import argparse
import math
import socket
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.common.packets import encode_packet  # noqa: E402

NUM_SHAPES = 8
SHAPE_NAMES = [f"soakShape{i}" for i in range(NUM_SHAPES)]


def synthetic_packet(t_ms: int, phase: float) -> bytes:
    """One deterministic synthetic frame driven by ``phase`` (seconds)."""
    shapes = {}
    for i, name in enumerate(SHAPE_NAMES):
        freq = 0.11 + 0.07 * i  # slow, varied frequencies
        value = 0.5 + 0.5 * math.sin(2.0 * math.pi * freq * phase + i * 0.7)
        shapes[name] = round(value, 4)
    pose = {
        "rx": 8.0 * math.sin(2.0 * math.pi * 0.05 * phase),
        "ry": 15.0 * math.sin(2.0 * math.pi * 0.031 * phase),
        "rz": 10.0 * math.cos(2.0 * math.pi * 0.043 * phase),
        "tx": 0.1 * math.sin(2.0 * math.pi * 0.02 * phase),
        "ty": 0.0,
        "tz": 0.05 * math.cos(2.0 * math.pi * 0.017 * phase),
    }
    return encode_packet(
        t=t_ms,
        engine="soak",
        conf=0.99,
        pose=pose,
        shapes=shapes,
        extra={"phase": round(phase, 4)},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RealCapture synthetic soak sender")
    parser.add_argument("--minutes", type=float, default=30.0, help="duration in minutes")
    parser.add_argument("--hz", type=float, default=30.0, help="target packet rate")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11111)
    parser.add_argument(
        "--stamp-skew-ms",
        type=int,
        default=0,
        help=(
            "measurement-integrity control: stamp each packet's t field N ms "
            "earlier than the real send time (t = now_ms - N) so the receiving "
            "gate must observe at least N ms of transport latency. This shifts "
            "timestamps only and leaves the send rate untouched; it is NOT a "
            "network simulation and injects no real delay."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.hz <= 0 or args.minutes <= 0:
        parser.error("--hz and --minutes must be positive")
    target_interval = 1.0 / args.hz
    duration_s = args.minutes * 60.0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start = time.monotonic()
    sent = 0
    errors = 0
    next_send = start
    print(
        f"Soak sender: {args.minutes:g} min @ {args.hz:g} Hz -> udp {args.host}:{args.port} "
        f"(Ctrl+C to stop early)"
    )
    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            if elapsed >= duration_s:
                break
            if now < next_send:
                time.sleep(max(0.0, next_send - now))
            next_send += target_interval
            # --stamp-skew-ms shifts the wire timestamp only (measurement
            # integrity control), never the send schedule.
            t_ms = int(time.time() * 1000) - args.stamp_skew_ms
            try:
                sock.sendto(synthetic_packet(t_ms, elapsed), (args.host, args.port))
                sent += 1
            except OSError as exc:
                errors += 1
                if errors <= 5 or errors % 500 == 0:
                    print(f"send error ({errors} so far): {exc}", file=sys.stderr)
            if args.verbose and sent % (int(args.hz) * 60) == 0 and sent > 0:
                rate = sent / (time.monotonic() - start)
                print(f"sent={sent} rate={rate:.2f} Hz elapsed={time.monotonic() - start:.0f}s")
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)

    total_elapsed = time.monotonic() - start
    rate = sent / total_elapsed if total_elapsed > 0 else 0.0
    print(
        f"Done. packets={sent} elapsed={total_elapsed:.1f}s rate={rate:.2f} Hz "
        f"(target {args.hz:g}) send_errors={errors}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

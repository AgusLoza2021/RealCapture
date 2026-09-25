"""OpenSeeFace capture backend: spawns facetracker, re-encodes to RealCapture packets.

Design (TDD section 5): OpenSeeFace's facetracker runs as an external process
and sends its own UDP stream; this backend listens on the tracker's target
port, parses the binary protocol (see openseeface_protocol.py), and forwards
standard RealCapture packets to Blender.

OpenSeeFace carries its own native expression features (14 SVM-derived
channels), not ARKit-52. Channels are forwarded verbatim under their upstream
names plus ``eyeOpennessLeft``/``eyeOpennessRight``; the private mapping layer
is responsible for converting them to rig profiles.

Requires the OpenSeeFace tracker (facetracker.exe or facetracker.py) — not
installed by this project. Pass its location via --osf-command.
"""

from __future__ import annotations

import shlex
import socket
import subprocess
import time

from ..common.packets import Packet
from .base import CaptureBackend, logger
from .openseeface_protocol import OsfFace, OsfPacketError, parse_osf_datagram

DEFAULT_OSF_PORT = 11573  # facetracker's default target port


def face_to_packet(face: OsfFace, engine: str = "openseeface") -> Packet:
    """Convert one parsed OpenSeeFace face into a RealCapture packet.

    The tracker timestamp is UTC seconds; packets need epoch milliseconds.
    Pose is forwarded raw (OSF conventions): euler in degrees, translation in
    camera units. Axis-convention normalization is the mapping layer's job.
    """
    shapes: dict[str, float] = {
        "eyeOpennessRight": face.right_eye_open,
        "eyeOpennessLeft": face.left_eye_open,
    }
    shapes.update(face.features)

    return Packet(
        t=int(round(face.time * 1000.0)),
        engine=engine,
        conf=1.0 if face.success else 0.0,
        pose={
            "rx": face.euler[0],
            "ry": face.euler[1],
            "rz": face.euler[2],
            "tx": face.translation[0],
            "ty": face.translation[1],
            "tz": face.translation[2],
        },
        shapes=shapes,
        extra={
            "osf": {
                "face_id": face.id,
                "success": face.success,
                "pnp_error": face.pnp_error,
                "camera_resolution": list(face.camera_resolution),
                "quaternion": list(face.quaternion),
            }
        },
    )


class OpenSeeFaceBackend(CaptureBackend):
    """Runs facetracker as a subprocess and relays its UDP stream as RealCapture packets."""

    backend_name = "openseeface"

    def __init__(
        self,
        camera_index: int = 0,
        fps: int = 30,
        udp_host: str = "127.0.0.1",
        udp_port: int = 11111,
        osf_command: str = "",
        osf_ip: str = "127.0.0.1",
        osf_port: int = DEFAULT_OSF_PORT,
    ) -> None:
        super().__init__(camera_index=camera_index, fps=fps, udp_host=udp_host, udp_port=udp_port)
        self._osf_command = osf_command
        self._osf_ip = osf_ip
        self._osf_port = osf_port
        self._osf_socket: socket.socket | None = None
        self._process: subprocess.Popen | None = None
        self.osf_packets_seen = 0
        self.osf_packets_invalid = 0

    def run_loop(self) -> None:
        if not self._osf_command:
            raise RuntimeError(
                "No OpenSeeFace command configured. Pass --osf-command pointing at "
                "facetracker.exe (or a quoted 'python path/to/facetracker.py'). "
                "OpenSeeFace is BSD-2-Clause licensed and not bundled with RealCapture."
            )

        args = shlex.split(self._osf_command) + [
            "--ip", self._osf_ip,
            "--port", str(self._osf_port),
            "--silent", "1",
        ]
        try:
            self._process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise RuntimeError(f"failed to launch OpenSeeFace tracker: {exc}") from exc

        self._osf_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._osf_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._osf_socket.bind((self._osf_ip, self._osf_port))
        self._osf_socket.settimeout(0.5)
        logger.info(
            "openseeface tracker pid=%s sending to %s:%d; relaying to %s:%d",
            self._process.pid, self._osf_ip, self._osf_port, self.udp_host, self.udp_port,
        )

        min_interval = 1.0 / self.fps
        last_send = 0.0
        try:
            while self.running:
                if self._process.poll() is not None:
                    logger.error(
                        "openseeface tracker exited with code %s", self._process.returncode
                    )
                    break

                try:
                    data, _addr = self._osf_socket.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break

                self.osf_packets_seen += 1
                try:
                    parsed = parse_osf_datagram(data)
                except OsfPacketError as exc:
                    self.osf_packets_invalid += 1
                    logger.debug("dropping invalid openseeface datagram: %s", exc)
                    continue

                face = next((f for f in parsed.faces if f.id == 0), parsed.faces[0])
                packet = face_to_packet(face)

                now = time.monotonic()
                if (now - last_send) < min_interval:
                    continue  # fps cap: drop, never queue
                last_send = now
                self.send_packet(packet)
        finally:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
            if self._osf_socket is not None:
                self._osf_socket.close()
                self._osf_socket = None

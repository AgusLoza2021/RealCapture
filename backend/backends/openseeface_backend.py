"""OpenSeeFace capture backend (adapter planned for work unit C)."""

from __future__ import annotations

from .base import CaptureBackend


class OpenSeeFaceBackend(CaptureBackend):
    """Adapter for emilianavt/OpenSeeFace (BSD-2-Clause).

    Planned: spawn the upstream ``facetracker.py`` as a child process, parse its
    UDP protocol, and map it into the RealCapture packet schema.
    """

    backend_name = "openseeface"

    def run_loop(self) -> None:
        raise NotImplementedError("OpenSeeFace adapter planned for work unit C")

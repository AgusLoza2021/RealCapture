"""MediaPipe Face Landmarker capture backend.

Streams 52 ARKit-shaped blendshape scores plus the head-pose transform from a
standard RGB webcam, latest-frame-wins, at a capped fps.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from .base import BackendImportError, CaptureBackend
from ..common.packets import Packet

logger = logging.getLogger(__name__)

# Official float16 face_landmarker task bundle (Apache-2.0, redistributable).
FACE_LANDMARKER_TASK_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"

# Attribute paths under the mediapipe module that expose BaseOptions, in
# preference order: the canonical tasks.python location, its tasks-level
# re-export (mediapipe 1.x aliases tasks -> tasks.python), then the legacy
# tasks.vision re-export (mediapipe 0.10.x).
_BASE_OPTIONS_CANDIDATE_PATHS: tuple[tuple[str, ...], ...] = (
    ("tasks", "python", "BaseOptions"),
    ("tasks", "BaseOptions"),
    ("tasks", "vision", "BaseOptions"),
)


def resolve_base_options(mp_module: Any) -> Any:
    """Resolve the ``BaseOptions`` class from a mediapipe module object.

    Pure and side-effect free (no real mediapipe import at module scope) so it
    is unit-testable with stub namespaces. Mediapipe 1.0 removed the legacy
    ``mediapipe.tasks.vision.BaseOptions`` re-export and aliased
    ``mediapipe.tasks`` to ``mediapipe.tasks.python``, so the symbol is looked
    up by capability across known layouts instead of by version number.

    Raises AttributeError naming the version and every location tried if none
    of the candidates resolve.
    """
    tried: list[str] = []
    for path in _BASE_OPTIONS_CANDIDATE_PATHS:
        obj: Any = mp_module
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        if obj is not None:
            return obj
        tried.append("mediapipe." + ".".join(path))
    version = getattr(mp_module, "__version__", "unknown")
    raise AttributeError(
        f"mediapipe {version} does not expose BaseOptions at any known location "
        f"(tried: {', '.join(tried)}). Check that the installed mediapipe is "
        "compatible with backend/requirements.txt."
    )


def _matrix_to_euler_degrees(matrix: Any) -> dict[str, float]:
    """Extract rotation (rx, ry, rz) in degrees from a 4x4 transform matrix."""
    r = [
        [float(matrix[0][0]), float(matrix[0][1]), float(matrix[0][2])],
        [float(matrix[1][0]), float(matrix[1][1]), float(matrix[1][2])],
        [float(matrix[2][0]), float(matrix[2][1]), float(matrix[2][2])],
    ]
    # Standard roll-pitch-yaw extraction (XYZ intrinsic).
    sy = math.sqrt(r[0][0] * r[0][0] + r[1][0] * r[1][0])
    singular = sy < 1e-6
    if not singular:
        rx = math.atan2(r[2][1], r[2][2])
        ry = math.atan2(-r[2][0], sy)
        rz = math.atan2(r[1][0], r[0][0])
    else:
        rx = math.atan2(-r[1][2], r[1][1])
        ry = math.atan2(-r[2][0], sy)
        rz = 0.0
    return {
        "rx": math.degrees(rx),
        "ry": math.degrees(ry),
        "rz": math.degrees(rz),
    }


class MediaPipeBackend(CaptureBackend):
    """MediaPipe Face Landmarker backend (default engine)."""

    backend_name = "mediapipe"

    def __init__(self, model_path: str | Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self._mailbox: list[Any] = []  # size-1 mailbox under lock (latest-frame-wins)
        self._mailbox_lock = threading.Lock()
        self._last_timestamp_ms = 0

    # -- heavy dependency handling -------------------------------------------

    def _lazy_imports(self):
        try:
            import cv2  # noqa: F401
            import mediapipe as mp
        except ImportError as exc:
            raise BackendImportError(
                "MediaPipe/OpenCV not installed. Create the backend venv and run: "
                "pip install -r backend/requirements.txt "
                "(see backend/README.md)"
            ) from exc
        return mp, cv2

    def _ensure_model(self) -> Path:
        if self.model_path.exists():
            return self.model_path
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading face_landmarker.task from %s ...", FACE_LANDMARKER_TASK_URL)
        tmp_path = self.model_path.with_suffix(".task.part")
        urllib.request.urlretrieve(FACE_LANDMARKER_TASK_URL, tmp_path)  # noqa: S310 - fixed official URL
        tmp_path.replace(self.model_path)
        logger.info("Model saved to %s", self.model_path)
        return self.model_path

    # -- capture loop ---------------------------------------------------------

    def run_loop(self) -> None:
        mp, cv2 = self._lazy_imports()
        model_path = self._ensure_model()

        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode
        BaseOptions = resolve_base_options(mp)

        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=VisionRunningMode.LIVE_STREAM,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            result_callback=self._on_result,
        )

        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open camera index {self.camera_index}")

        min_frame_interval = 1.0 / float(self.fps)
        logger.info("Camera %d opened; capture loop running at <=%d fps", self.camera_index, self.fps)
        try:
            with FaceLandmarker.create_from_options(options) as landmarker:
                while self.running:
                    loop_start = time.monotonic()

                    ok, frame = cap.read()
                    if not ok:
                        # Transient read failure: do not spin, do not queue.
                        time.sleep(0.05)
                        continue

                    # Publish the raw BGR frame for the camera preview BEFORE
                    # the RGB conversion: the injected encoder expects what
                    # cv2 produced. Defensive: a raising observer must never
                    # break capture.
                    self.notify_frame(frame)

                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    timestamp_ms = self._next_timestamp_ms()
                    landmarker.detect_async(mp_image, timestamp_ms)

                    self._drain_and_send()

                    # Cap the loop rate; inference lag naturally drops frames.
                    elapsed = time.monotonic() - loop_start
                    sleep_for = min_frame_interval - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)
        finally:
            cap.release()
            logger.info("Camera %d released", self.camera_index)

    def _next_timestamp_ms(self) -> int:
        # MediaPipe LIVE_STREAM requires strictly increasing timestamps.
        now_ms = int(time.monotonic() * 1000)
        self._last_timestamp_ms = max(now_ms, self._last_timestamp_ms + 1)
        return self._last_timestamp_ms

    def _on_result(self, result, output_image, timestamp_ms) -> None:  # noqa: ANN001 - mediapipe signature
        """Mediapipe callback: store ONLY the newest result (mailbox size 1)."""
        with self._mailbox_lock:
            self._mailbox = [result]

    def _drain_and_send(self) -> None:
        with self._mailbox_lock:
            mailbox, self._mailbox = self._mailbox, []
        if not mailbox:
            return
        result = mailbox[0]
        packet = self._result_to_packet(result)
        if packet is not None:
            self.send_packet(packet)

    def _result_to_packet(self, result) -> Packet | None:  # noqa: ANN001
        if not result.face_blendshapes:
            return None  # no face detected this cycle

        shapes: dict[str, float] = {}
        for category in result.face_blendshapes[0]:
            if category.category_name:
                shapes[category.category_name] = max(0.0, min(1.0, float(category.score)))

        pose = {key: 0.0 for key in ("rx", "ry", "rz", "tx", "ty", "tz")}
        if result.facial_transformation_matrixes:
            matrix = result.facial_transformation_matrixes[0]
            pose.update(_matrix_to_euler_degrees(matrix))
            pose["tx"] = float(matrix[0][3])
            pose["ty"] = float(matrix[1][3])
            pose["tz"] = float(matrix[2][3])

        return Packet(
            t=int(time.time() * 1000),
            engine=self.backend_name,
            conf=1.0,  # landmarker reports no per-face confidence; presence implies 1.0
            pose=pose,
            shapes=shapes,
        )

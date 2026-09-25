# RealCapture backend (capture engines)

External capture process for RealCapture. Runs MediaPipe Face Landmarker (or,
later, OpenSeeFace) against a webcam and streams validated JSON packets to the
Blender addon over UDP.

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt  # dev only (pytest)
```

The first run downloads the official `face_landmarker.task` model bundle
(Apache-2.0) into `backend/models/`.

## Run

```bash
python run_capture.py --engine mediapipe --camera 0 --fps 30 --port 11111
```

The process prints a startup line, then streams packets until Ctrl+C. On exit
it reports packets sent, elapsed time, average fps, and send errors.

## Packet format (UDP/JSON, one datagram per frame)

```json
{
  "t": 1718345678901,
  "engine": "mediapipe",
  "conf": 0.97,
  "pose": {"rx": 0.0, "ry": 12.5, "rz": -3.2, "tx": 0.1, "ty": -0.05, "tz": 0.0},
  "shapes": {"eyeBlinkLeft": 0.42, "jawOpen": 0.18},
  "extra": {}
}
```

- `pose` rotations are degrees; translations are model-space units.
- `shapes` values are clamped to 0..1.
- Schema is validated on both ends (`backend/common/packets.py`).

## Engines

| Engine | Status | Notes |
|---|---|---|
| MediaPipe Face Landmarker | Implemented | 52 ARKit-shaped blendshapes + head pose, LIVE_STREAM mode, latest-frame-wins |
| OpenSeeFace | Planned (work unit C) | Adapter for emilianavt/OpenSeeFace (BSD-2-Clause) |

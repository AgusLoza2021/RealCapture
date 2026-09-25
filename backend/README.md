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
| OpenSeeFace | Implemented | Adapter for emilianavt/OpenSeeFace (BSD-2-Clause), not bundled |

## OpenSeeFace engine

OpenSeeFace is not bundled (license policy) — download it from the upstream
repository (emilianavt/OpenSeeFace) and point `--osf-command` at its tracker:

```bash
# Windows binary release:
python run_capture.py --engine openseeface --osf-command "C:/OSF/Binary/facetracker.exe"

# Or via Python:
python run_capture.py --engine openseeface --osf-command "python C:/OSF/facetracker.py"
```

The backend spawns the tracker (silenced), listens on the tracker's target
port (`--osf-port`, default 11573), and relays its binary stream as standard
RealCapture packets. OpenSeeFace channels are forwarded under their native
names (`mouth_open`, `eyebrow_updown_l`, ...) plus `eyeOpennessLeft/Right`;
head pose uses OSF conventions (euler degrees, camera-space translation).
Converting native channels to a rig profile is the mapping layer's job, not
the transport's.

## Soak testing (no camera needed)

`tools/soak_send.py` streams deterministic synthetic packets for long-running
stability sessions:

```bash
python tools/soak_send.py --minutes 30 --hz 30 --port 11111
```

Enable the addon, press Start (optionally with Record Session on), let it run,
then check: applied FPS stability, transport latency, Blender responsiveness,
and memory over time. A session file from a soak run is the M1 exit evidence.

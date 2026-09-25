# RealCapture Blender addon

Consumer side of RealCapture. Receives facial-capture packets from the
external backend process and drives the scene in real time, with zero threads
touching `bpy` (all work happens in `bpy.app.timers` on the main thread).

Requires **Blender 4.2 LTS** or newer.

## Install

1. Edit > Preferences > Add-ons > Install…
2. Select this folder (`addon/`) as a ZIP (or install from disk on 4.2+).
3. Enable **RealCapture**.

## Quick start

1. In the 3D viewport, open the sidebar (N) > **RealCapture** tab.
2. Create an Empty (Shift+A > Empty > Plain Axes) and assign it as **Controller**.
3. Start the backend in a terminal (see `backend/README.md`).
4. Press **Start**. Live telemetry shows engine, applied FPS, packet count,
   and transport latency (avg/max).
5. Stop with **Stop** (or let the panel report a crash — the timer self-stops).

## How values reach your rig

The addon writes **custom properties** on the controller empty — it never
touches shape keys or bones directly. You bind them with **native drivers**:

| Property | Meaning |
|---|---|
| `rc_shape_<name>` | Expression channels. MediaPipe: ARKit-52 names (`jawOpen`, `eyeBlinkLeft`, …). OpenSeeFace: native channel names plus `eyeOpennessLeft/Right`. |
| `rc_pose_rx/ry/rz` | Head rotation in degrees (engine conventions). |
| `rc_pose_tx/ty/tz` | Head translation (engine conventions). |
| `rc_meta_conf` | Latest packet confidence (0..1). |
| `rc_meta_engine` | Engine name of the latest packet. |

Example: select your shape key, add a driver of type *Single Property* with
`["rc_shape_jawOpen"]` on the controller Empty. No Python expressions needed.

**Epsilon** skips property writes when a value changes less than the given
amount, reducing depsgraph churn on subtle noise.

## Session record / replay

- **Record Session**: while capturing, every applied packet is appended to
  **Session File** (JSONL, arrival-timed). Blend-relative paths (`//…`) work.
- **Replay Session**: feeds a recorded session back through the exact same
  application path (epsilon gating, stats, controller writes) with the
  original inter-arrival timing. Useful for debugging rigs without a camera
  and for reproducible rig tuning.
- Replay stops itself when the session ends; malformed lines are skipped and
  reported.

Session files are plain JSONL — one header line, then
`{"recv_t": <epoch ms>, "packet": {...}}` per packet — so you can inspect,
diff, or post-process them with any tool.

## Architecture notes

- `schema.py` is a byte-identical mirror of the backend packet schema
  (guarded by `tests/test_schema_sync.py`).
- `receiver.py` / `telemetry.py` / `session.py` are pure Python (no `bpy`)
  and unit-tested; Blender-specific code is confined to `consumer.py`,
  `properties.py`, and `ui.py`, loaded lazily at registration.
- The UDP receiver drains its socket queue every tick and keeps only the
  newest packet (latest-frame-wins): an old frame is worse than a dropped one.

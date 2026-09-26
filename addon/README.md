# RealCapture Blender addon

Consumer side of RealCapture. Receives facial-capture packets from the
external backend process and drives the scene in real time, with zero threads
touching `bpy` (all work happens in `bpy.app.timers` on the main thread).

Requires **Blender 4.2 LTS** or newer.

## Install

1. Edit > Preferences > Add-ons.
2. Open the drop-down menu at the top right of the Add-ons section and choose
   **Install from Disk…**.
3. Select this repository's `addon/` folder — Blender 4.2+ accepts an add-on
   folder directly (a ZIP of the folder works the same way).
4. Enable **RealCapture** in the add-on list.

The addon registers as **RealCapture** (category *Animation*) and declares a
Blender floor of 4.2.0, so older Blender versions will not list it.

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

## Rig Connector (setup wizard)

The Rig Connector binds a rigged face model in a few clicks — scan, review,
bind, unbind. It implements the workflow validated in
`docs/research/rig-mapping-workflow-landscape.md` with original code.

### Workflow

1. **Assign targets** in the *Rig Connector* panel: the face **Mesh** (with
   shape keys), the **Armature**, and optionally the **Head Bone** (blank =
   auto-detect).
2. **Scan & Auto-Match**: the addon scans shape keys and bones, standardizes
   names (prefixes, separators, side markers), and matches them against
   per-channel alias lists (ARKit names, Rigify/FaceIt-style fragments,
   VRM/MMD conventions). Matches are confidence-scored and assigned
   one-to-one.
3. **Review the table**: every proposal shows as `channel -> detected control`
   with its confidence. Untick anything wrong — nothing is applied until you
   confirm.
4. **Build & Bind** creates:
   - **Face Point empties** (`RC_pt_<role>`, collection *RealCapture Points*)
     parented to the head bone — jaw, eyelids, brows, mouth corners, lips,
     cheeks, eyes;
   - **shape key drivers** reading the controller properties, implemented as
     GENERATOR f-curve modifiers (no scripted expressions, no security
     prompts);
   - **bone constraints** (`RC_follow_<role>`) making facial bones follow the
     face points.

   The profile is saved to **Rig Profile** (versioned JSON) for reuse.
5. **Reposition the empties** in the viewport to fit the face (they stay
   parented to the head bone). Gains, axes and channels live in the profile
   JSON (`addon/presets/example_rigify_style.json` is a working example).
6. **Unbind** removes every RealCapture driver, constraint and face-point
   empty in one click. Idempotent and safe on any scene.

**Load Profile & Bind** re-applies a saved profile to any scene with the same
rig naming (e.g. another character built with the same base rig).

### How face points work

Each face point is an empty whose rest transform is frozen at bind time; while
capturing, the addon offsets it per channel (`rest + gain * value`, additive
across channels, so gaze combines look-in/out with look-up/down). Bones follow
through ordinary constraints the artist can inspect or edit. The point set is
part of the mapping layer — the UDP packet schema is unchanged.

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
- `receiver.py` / `telemetry.py` / `session.py` / `rigprofile/*` are pure
  Python (no `bpy`) and unit-tested; Blender-specific code is confined to
  `consumer.py`, `binding.py`, `wizard.py`, `properties.py`, and `ui.py`,
  loaded lazily at registration.
- The UDP receiver drains its socket queue every tick and keeps only the
  newest packet (latest-frame-wins): an old frame is worse than a dropped one.

# Feature: Control Room window (camera preview + connection status)

Phase 1 of the owner's onboarding plan. Goal: one place the user looks to answer two questions —
**what is connected, and is it working** — and to see **their own face** while the rig moves.

Owner's requirements, verbatim in intent:
- a UI to see our camera;
- a list of connections (camera, Blender, ...) with **traffic-light colours** (green / red / yellow)
  so the user knows the status;
- a **nice-looking** window for the tool.

Phase 2 (the modular rig targets) starts only once this window exists: `modular-rig-targets.md`.

## What already exists (verified, not assumed)

`backend/dashboard/` already runs: `hub.py` (pure state machine + ring buffers + broadcast),
`server.py` (FastAPI + WebSocket at ~10 Hz + REST), `static/index.html` (single dark page:
status header, FPS sparkline, top active channels). `--dashboard PORT` serves it on the LAN and
prints the phone-usable address (`backend/run_capture.py:124`). `fastapi`/`uvicorn` are already
optional extras. Its own task doc `companion-dashboard.md` has U1–U4 all checked.

So this is an **upgrade of an existing surface**, not a new app. What is missing is exactly the two
things the owner asked for:

| Gap | Evidence |
| --- | --- |
| **No camera frame is exposed anywhere.** No JPEG encode, no MJPEG endpoint, no frame in the WS snapshot. `--visualize` is advertised (`run_capture.py:42`) and is a no-op (`:135-136`). | grep for `imencode|jpeg|video_feed|frame|preview` over `backend/dashboard`, `run_capture.py`, `mediapipe_backend.py` returns only that stub. |
| **Blender never talks back.** The addon's receiver is receive-only (`addon/receiver.py:31`); the hub's status is only the backend's own `IDLE/RUNNING/STOPPED` (`hub.py:63`). A "Blender" light therefore has **no data source at all** today. | `addon/receiver.py:31`; `hub.py:63,176`. |

The second one is the real design problem in this feature: the owner wants a light he can trust,
and the light needs a signal that does not exist yet.

## Decisions

- **Reuse the existing dashboard; do not start a second UI stack.** No Electron, no Tauri, no Qt.
  The stack already reaches the phone over the LAN, which is also the owner's demo vehicle.
- **The window is the dashboard in browser app mode** (`msedge --app=http://host:port`), which gives
  a real window with no new dependency, and the same UI stays reachable from the phone.
  *Owner may veto this; nothing else in this plan depends on it.*
- **The camera preview is MJPEG over its own endpoint**, not base64 inside the 10 Hz WebSocket
  snapshot. Rationale: the browser decodes MJPEG natively, the camera stream cannot starve the
  telemetry stream, and a stalled viewer cannot grow a queue.
- **The Blender back-channel reuses the socket pair that already exists.** `recvfrom` already hands
  the addon the sender's address, so a small heartbeat datagram back to it needs **no new port and
  no handshake**. It also carries the bind report, so the UI can show *how* the rig is bound
  (shape-keys-only vs bones, and how many channels), not just that it is alive.
- **Traffic-light semantics are owner-visible language, so they get one definition each**, not ad-hoc
  colouring: green = fresh signal within the last N seconds; yellow = connected but stale or
  degraded (with the reason printed); red = absent or failed (with the reason printed). A light
  never goes green because nothing has told it otherwise — that is the "success-looking silence"
  defect this project keeps paying for.
- **No auth, no remote exposure.** Same LAN-only posture as the existing dashboard. Not a new
  decision; recording it so it is not silently changed later.

## Work units

Not started. Order matters: the data feeds are needed in every UI variant, and they are also the
only part that can be built and tested before the visual design exists.

- [ ] W1. **Frame tap (pure logic).** A bounded single-slot "latest frame" holder fed by the capture
  loop, so a slow consumer can never queue 30 fps of frames in memory. Unit-tested with a fake frame
  source, no cv2 and no real camera.
- [ ] W2. **Frame transport.** JPEG encode at a capped rate (target ≤15 fps, quality tuned for a
  face), served as `multipart/x-mixed-replace` on `/camera.mjpg`, plus a REST `GET /camera.jpg` for
  one-shot. Bounded: when nobody is watching, nothing is encoded.
- [ ] W3. **Blender back-channel.** The addon answers the sender's address with a small heartbeat
  carrying its bind report; the backend derives green/yellow/red from heartbeat freshness. Must not
  block the addon's consumer loop, must not break the existing one-way path, and must be honest
  when Blender is simply not open.
- [ ] W4. **Connection list model (pure logic).** Signals (camera, packets-out, Blender heartbeat,
  recording) mapped to `{state, reason}`, unit-tested as a truth table. This is the unit that makes
  the lights trustworthy.
- [ ] W5. **The window itself.** Read the `frontend-design` skill before writing markup; camera panel,
  connection cards, existing telemetry, and a first-run empty state that says what to do next.
- [ ] W6. **Launch + docs.** A double-clickable path to the window (app mode) and a short doc; the
  existing `camera-to-rig.cmd` flow gains the dashboard flag.

## Non-goals

- No rig configuration UI here (that is phase 2).
- No native desktop shell, no installer, no packaging.
- No authentication, no internet exposure.
- Not fixing the missing character generator or the preflight doctor — those are the separate
  onboarding blockers recorded in the onboarding audit and stay their own slice.

## Open questions

1. Window technology: app-mode window (recommended) vs plain browser tab vs native shell.
2. Does the camera preview need to work when capture is stopped (a "camera check" before starting)?
   Cheap to add in W2, but it changes the lifetime of the frame source.
3. Heartbeat staleness threshold (green→yellow). Proposed: yellow after ~2 s, red after ~5 s.

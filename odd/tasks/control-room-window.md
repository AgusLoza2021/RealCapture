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

- [x] W1. **Frame tap (pure logic).** A bounded single-slot "latest frame" holder fed by the capture
  loop, so a slow consumer can never queue 30 fps of frames in memory. Unit-tested with a fake frame
  source, no cv2 and no real camera.
- [x] W2. **Frame transport.** JPEG encode at a capped rate (target ≤15 fps, quality tuned for a
  face), served as `multipart/x-mixed-replace` on `/camera.mjpg`, plus a REST `GET /camera.jpg` for
  one-shot. Bounded: when nobody is watching, nothing is encoded.
- [x] W3. **Blender back-channel.** The addon answers the sender's address with a small heartbeat
  carrying its bind report; the backend derives green/yellow/red from heartbeat freshness. Must not
  block the addon's consumer loop, must not break the existing one-way path, and must be honest
  when Blender is simply not open.
- [x] W4. **Connection list model (pure logic).** Signals (camera, packets-out, Blender heartbeat,
  recording) mapped to `{state, reason}`, unit-tested as a truth table. This is the unit that makes
  the lights trustworthy.
- [x] W5. **The window itself.** Read the `frontend-design` skill before writing markup; camera panel,
  connection cards, existing telemetry, and a first-run empty state that says what to do next.
- [x] W6. **Launch + docs.** A double-clickable path to the window (app mode) and a short doc; the
  existing `camera-to-rig.cmd` flow gains the dashboard flag.

## Evidence — W1 and W2 delivered

One work unit, ending in something a human can open: `GET /camera.mjpg` streams the camera as
`multipart/x-mixed-replace`, and `GET /camera.jpg` returns one snapshot. Verified by the parent,
not taken from the writer's report.

| what | where |
| --- | --- |
| pure tap, no cv2 and no numpy | `backend/dashboard/frametap.py` (`FrameTap`, `should_encode`, `clamp_stream_fps`, `MAX_STREAM_FPS = 15`) |
| endpoints | `backend/dashboard/server.py` — `/camera.mjpg`, `/camera.jpg`; both answer 503 with a plain-text reason naming the missing thing instead of starting a healthy-looking empty stream |
| frame source | `backend/backends/base.py` (`on_frame` hook, `notify_frame`) and `backend/backends/mediapipe_backend.py` (publishes the raw BGR frame before the RGB conversion, once per captured frame) |
| wiring | `backend/run_capture.py` — the tap is built with the injected JPEG encoder (downscale to 640 px, cv2 imported lazily inside the closure) and passed to `create_app`; one new flag, `--stream-fps` (default 12) |
| tests | `tests/test_frametap.py`, `tests/test_camera_stream.py` |

`python -m pytest tests -q` → **237 passed, 1 warning** (was 210 before this work unit). The suite runs
on the system Python, which has no cv2: the tap and the endpoints are exercised with fakes, and the
lazy cv2 import inside the encoder is what keeps that possible. Do not "fix" it into a module-level import.

Measured, with numbers the parent reproduced independently (500 frames at 30 fps, cap 15): **zero
subscribers → 0 calls to the encoder**; one subscriber → non-zero. That is the "idle means no encode"
requirement, and it is the behaviour most likely to regress silently, so it is asserted directly.
`--stream-fps` clamps: 12 → 12, 60 → 15, 0 → 1, -3 → 1, 1000 → 15. It cannot exceed 15.

### Two decisions taken while building it

- **The cap is a cap, not a target.** Measured through the ASGI app, the stream lands at roughly
  10.8 fps rather than 15: after each encode the generator re-polls, so every frame pays the poll
  interval on top of the minimum interval. It never exceeds the cap, which is the property that
  protects the machine, and a preview a few frames short of 15 is invisible. Recorded here so nobody
  later reads the gap as a leak. If it ever matters, the fix is to track `next_encode_t = last + interval`
  rather than to sprinkle an epsilon.
- **The stream ends honestly after about five seconds with no fresh frame** instead of re-looping the
  last frame forever. A frozen face looks alive; a broken image does not. The cost is a visibly broken
  image when capture stops, and W4 must carry the reason as text in the window so the silence is named.

### Not verified (stated, not implied)

- **The live path.** There is no camera in this environment, so `cap.read()` → publish → `cv2.imencode`
  with `backend/.venv`, and the endpoint under a real `uvicorn`, were never executed. Everything above
  is exercised through the ASGI app with fake frames. This is the same unproven link as
  `camera-to-rig.cmd`: it needs the owner's face in front of a real camera.
- The 503 branch for "tap present but no encoder bound" has no dedicated test.

## Frozen contract — decided by the parent, not by the writers

W3, W4 and W5 run as three writers over disjoint file sets. They can only stay disjoint if the
interface between them is frozen before they start. This section is that interface. Change it here
first, then change the code.

### Raw facts the backend can know

Interpretation-free values, each owned by whoever produces it:

- `camera_last_frame_age_s: float | None` — seconds since the capture loop last handed over a frame.
- `packets_out: int`, `packets_last_age_s: float | None` — from the existing hub telemetry.
- `blender_heartbeat_age_s: float | None` — seconds since the addon last answered. None means never.
- `blender_bind: dict | None` — the addon's bind report, exactly as the addon sent it.
- `record_active: bool`.

### What the snapshot carries

`hub.snapshot()` gains one key, also reachable through `/api/status` and the `/ws` snapshot:

```
"connections": [
  {"id": "camera",  "label": "Camera",              "state": "green|yellow|red",
   "reason": "", "detail": {}},
  {"id": "packets", "label": "Packets to Blender",  ...},
  {"id": "blender", "label": "Blender rig",         ...}
]
```

- `reason` MUST be a non-empty string whenever `state != "green"`. Enforced by construction in one
  function and tested by mutation: a check that cannot fail is not a check.
- `detail` is free-form per `id` and may be empty. The UI must never depend on its inner shape to
  decide a colour.
- Consumers must treat `connections` as OPTIONAL: an older backend, or a snapshot taken before the
  model was wired, must render as explicitly unknown, never as green.

### The truth table (W4 owns it, W5 only displays it)

Two thresholds per signal, module constants with names, pinned by tests:

| signal | fresh (green below) | stale (red above) | yellow |
| --- | --- | --- | --- |
| camera frame age | 1.0 s | 2.0 s | between the two |
| packets last arrival | 1.0 s | 2.0 s | between the two |
| Blender heartbeat age | 2.0 s | 5.0 s | between the two |

- `FRESH_S < STALE_S`, asserted.
- A signal that is absent or unknown is **red with a reason**, never green. Nothing goes green
  because nothing told it otherwise.
- **The light reports the health of the bind IN EFFECT, not of an attempt that was refused.**
  `bind_profile` measures a point/bone attempt, refuses it when it exceeds the 0.25 m rest gate, tears
  it down, and only then measures the residual. Reporting the refused attempt's number as the bind's
  health would paint a perfectly working shape-keys bind yellow forever. A permanent false alarm costs
  exactly what a false green costs: it teaches the owner to stop reading the light.
- So: `rest_displacement_m` in the datagram means **the bind in effect** — for `point_bones` the
  measured attempt, for `shape_keys` after a refusal the residual left by the revert, and null when
  the bind involves no bone path at all. The refusal evidence travels separately, in
  `refused_rest_displacement_m`.
- green: heartbeat fresh, `channels > 0`, and `rest_displacement_m` null or within 0.25 m. An
  informational reason IS allowed on green, and should be used: "shape keys only; the bone path was
  refused because it would have moved the mesh 0.83 m at rest".
- yellow: heartbeat fresh but degraded — `mode == "none"` (Blender is open and nothing is bound), or
  `rest_displacement_m > 0.25` (a revert that left damage behind). The reason names it.
- red: heartbeat missing or older than its stale threshold, or an **active** `point_bones` bind
  measuring above 0.25 m (a torn bind actually in use).
- A refused bone path with a working fallback is **not** by itself a fault: it is the T9 gate doing
  its job. It belongs in the reason text, not in the colour.

### The back-channel datagram (W3 owns both ends)

The addon answers the address `recvfrom` already gave it — no new port, no handshake. One JSON
datagram, one line, best effort:

```
{"rc_heartbeat": 1, "t_send_ms": <int>, "revision": <int>,
 "bind": {"mode": "shape_keys|point_bones|none",
          "channels": <int>,
          "head_bone": <str|null>,                    <- only while the bone path actually drives
          "rest_displacement_m": <float|null>,         <- the bind IN EFFECT
          "refused_rest_displacement_m": <float|null>, <- the rejected point/bone attempt
          "skip_reason": "no_armature|no_head_bone|rest_gate"|null} | null}
```

`rest_displacement_m` and `refused_rest_displacement_m` are different numbers and conflating them is
the defect this section was amended to prevent. On the reference MPFB2 character the refused attempt
measures about 0.83 m and the revert leaves a residual near zero: the correct report is
`mode: shape_keys`, `channels: 52`, `rest_displacement_m: <residual>`,
`refused_rest_displacement_m: 0.83`, `skip_reason: "rest_gate"`, which is a healthy, working rig.

- `rc_heartbeat: 1` is the discriminator: an unrelated datagram must be rejected, not guessed at.
- Cadence at most ~2 Hz, only while the consumer loop is alive, and it must never block that loop:
  a bounded best-effort send whose failure is logged once and never raised into the consumer.
- The datagram stays under 1200 bytes; when the bind report would exceed that, drop detail rather
  than split the message.
- The outbound packet format (backend to addon) is frozen and must not change. This datagram is the
  only new wire traffic, and it travels back on the same socket pair.

### Wiring, owned by the parent

W3 builds the listener and the tracker; W4 builds the model and lets the hub accept a blender
source; neither owns `run_capture.py` in this round, so the two-line handshake that connects them is
the parent's integration step, deliberately kept out of both writers' surfaces to avoid a
cross-dependency between concurrent writers.

## Evidence — W3, W4, W5 delivered

Three writers over disjoint file sets, against the frozen contract above. Reproduced by the parent,
not taken from the delivery notes.

**W3 — Blender answers back** (`addon/backchannel.py`, `addon/receiver.py`, `addon/consumer.py`,
`backend/dashboard/heartbeat.py`, `backend/backends/base.py`, `tests/test_backchannel.py`,
`tests/test_heartbeat.py`). The addon replies to the address `recvfrom` already returned, on the same
socket: no new port, no handshake, outbound packet format untouched.

- Parent's own end-to-end proof, with a listener socket bound to the sender's own port and a real
  headless Blender on the reference character: **50 heartbeats received** from `127.0.0.1:11111`,
  cadence min 0.468 s / avg 0.507 s / max 0.532 s (the ~2 Hz cap holds), 742 packets sent, Blender
  exited 0 with `MPFB LIVE OK`, `packets=741 fps=29.6`.
- Payload verbatim: `{"rc_heartbeat":1,"t_send_ms":...,"revision":1,"bind":{"mode":"shape_keys",
  "channels":52,"head_bone":null,"rest_displacement_m":2.4393007725113045e-07,
  "refused_rest_displacement_m":0.8318656335786587,"skip_reason":"rest_gate"}}`.
- **Defect caught and fixed during this phase, by the parent, in the contract itself.** The first
  delivery reported `rest_displacement_m: 0.8319` — the damage of the point/bone attempt *before* the
  T9 gate refused it. Taken as the bind's health, that paints a perfectly working shape-keys bind
  yellow forever, and a permanent false alarm costs exactly what a false green costs. The contract was
  amended: `rest_displacement_m` is now the bind **in effect** (for the refused path, the residual
  left by the revert — measured at 2.4e-07 m, i.e. the revert is clean) and the refused attempt
  travels in `refused_rest_displacement_m`. An anti-conflation test pins it.

**W4 — the lights** (`backend/dashboard/status_model.py`, `backend/dashboard/hub.py`). One pure truth
table, two thresholds per signal, and a single light constructor that raises rather than letting a
non-green light carry an empty reason. `hub.snapshot()` keeps every existing key and gains
`connections`; `/api/status` returns it unchanged (`server.py` needed no edit).

- Verified by the parent against the **real wire payload** above: the working rig is green *with* the
  refusal line as an informational reason; heartbeat 3 s old is yellow, 9 s old is red, never-heard is
  red with a reason; `mode: "none"` is yellow ("Blender is open but nothing is bound"); an active
  `point_bones` bind at 0.83 m is red; a camera frame 1.4 s old is yellow and a missing camera is red.
- Mutation proof supplied by the writer and re-run by the parent: with the invariant turned into a
  silent auto-fill, two tests fail; reverted, the suite is green.

**W5 — the window** (`backend/dashboard/static/index.html`, `tests/test_dashboard_ui.py`). One file,
inline CSS/JS, no framework, no CDN, no external URL (`grep` for `http://|https://` returns nothing).
Camera panel that only trusts the image while the camera light is green and otherwise covers it with
the reason text from `connections`; the four-state list (green/yellow/red/unknown) with state printed
as text as well as colour; a first-run empty state; telemetry and channels preserved; WS with a
polling fallback.

- `node --check` on the extracted inline script exits 0. **The rendering is unverified**: no browser
  was opened, so the visual result is reasoned, not observed. This is the honest gap.

**Wiring (parent-owned).** `_tap_camera_age` and `_HeartbeatSource` in `backend/run_capture.py` join
the tracker to the hub, kept out of both writers' surfaces to avoid a cross-dependency between
concurrent writers. `_HeartbeatSource` re-reads `backend.heartbeat` instead of snapshotting it,
because a restart replaces the tracker. `tests/test_run_capture_wiring.py` pins the late binding, and
the mutation (snapshot the tracker in the constructor) makes exactly that test fail.

**W8 additive seam (parent-owned).** `encode_or_reason(tap, frame)` at module level in
`backend/dashboard/server.py` is the single place that decides "can this frame be encoded, or is
there a reason to name". It is deliberately module level, and deliberately free of any cv2 import,
so a test can pin it without OpenCV and so the endpoints share one verdict instead of one honest
endpoint and one lying one.

Suite: **346 passed, 1 warning**.

**Still unverified at the end of this phase:** the window rendered in a real browser; the whole chain
with a live camera and a live face in front of it (no camera in the agent environment); the GUI timer
path in Blender (only the headless pumped-tick path ran).

## Evidence — W6 delivered (phase 1 complete)

`control-room.cmd` (repo root), `docs/control-room.md`, a pointer in `README.md`, and
`tests/test_control_room_launcher.py` (19 pinning tests, including three added by the parent).

- **Defect caught by the parent in the delivered launcher.** W6's whole point was "a window, not a browser
  tab". The delivered file decided app mode with `where msedge`, which **fails on this very machine** even
  though Edge is installed at `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` — a stock
  Windows install does not put Edge on PATH. The branch that would actually have run is the ordinary-tab
  fallback: the headline behaviour of the unit, silently replaced by a plausible-looking substitute, with no
  message. Fixed by probing the three install locations (machine x86, machine, per-user) before falling back
  to PATH, and by announcing the fallback when it does happen. Proven by running the launcher's own lines in
  cmd: `RESOLVED=[C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe]`.
- **Second defect: the doc contradicted the window.** It said UNKNOWN "is shown the same way as red". The
  window draws it as a hollow grey dot, deliberately unlike red, because "not known yet" is not "failed".
  Fixed in the doc and pinned by a test that compares the actual CSS rules, so collapsing the two states
  fails the suite.
- The failure path runs live on this camera-less machine: `control-room.cmd --no-browser --port 8799`
  reports that the pipeline never answered, names the likely causes, stops the capture, and exits **3**
  (`tasklist`/port check confirm nothing was left running). `--bogus` exits 2 with a usage line.
- Mutation proofs: drop the `ping`-based wait → the sleep test fails; rename the Edge path → the Edge test
  fails. Both reverted, suite green.
- Suite: **365 passed** (baseline at the start of W6: 346). The only warning is a third-party FastAPI/httpx
  deprecation, not ours.

**Gaps this phase ends with, stated rather than papered over:**

1. The **success path of the launcher has never run**: it needs a camera, and this machine has none, so
   "the server answers → the browser opens → a keypress stops the capture" is reasoned, not observed.
2. **No browser has been opened by anyone.** The window's appearance is still unverified.
3. The launcher's wait bound is 30 attempts of `ping -n 2` plus a probe, so it is "about 30 seconds" only at
   idle; under capture-startup load it stretches to a few minutes. It errs toward patience, not toward a
   false failure, and the doc does not promise a duration.

## Non-goals

- No rig configuration UI here (that is phase 2).
- No native desktop shell, no installer, no packaging.
- No authentication, no internet exposure.
- Not fixing the missing character generator or the preflight doctor — those are the separate
  onboarding blockers recorded in the onboarding audit and stay their own slice.

## W7 - first run in a real browser (three defects)

Phase 1 closed with the window "verified" by tests alone. The first real browser run
(Edge headless against a live camera) found three defects that every test had missed,
all of the same family: the suite judges the served document and the in-process
``TestClient``, never the path a human takes.

1. ``backend/run_capture.py`` used ``threading.Thread`` without importing ``threading``,
   so ``--dashboard`` raised ``NameError`` at ``_start_dashboard`` and the window could
   never be served from the real entry point. ``TestClient`` builds the app directly,
   so nothing in ``tests/`` touched that function.
2. ``backend/requirements.txt`` declared plain ``uvicorn``, which cannot serve ``/ws``
   without ``websockets`` or ``wsproto``. uvicorn refused every upgrade request
   ("No supported WebSocket library detected"), the page fell back to 1 s polling and
   kept showing live numbers, so the degradation was invisible from inside the app too.
   ``TestClient`` answers WebSocket connections in-process and never consults it.
3. ``<section id="camera-panel" hidden>`` was never unhidden by the script: the camera
   preview, the headline feature of the window, was unreachable in a browser no matter
   what the camera light said.

Evidence: ``/camera.jpg`` 200 with a 27 KB JPEG; ``/ws`` connected in 10 ms and pushed
228 snapshots in 8 s; the header read "capture running" instead of "reconnecting..."; the
rendered window showed the live camera image next to Camera GREEN, Packets GREEN and
Blender rig RED with its reason.

Lesson carried into phase 2: a green suite that never executes the branch the human
uses is not evidence about that branch. Add the browser to the verification loop for
any UI slice, and read a real rendering - never a reasoned one.

## W8 - the camera stream could answer 200 and send no bytes

Found while phase 2 was blocked on a live session, by reading the two camera endpoints side by
side. ``GET /camera.jpg`` already mapped an empty encode to a 503 naming the encoder
(``server.py:302-307`` before the fix), but ``GET /camera.mjpg`` guarded only with ``if data:``
inside the generator: an unbound encoder produced an endless 200 whose body never contained a
byte. The reachable shape is worse than the latent one - ``build_jpeg_encoder()`` always returns
a callable but imports cv2 lazily inside the closure (``server.py:85``), so on a host without
cv2 the ``ImportError`` was raised from inside the streaming generator, after 200 and the
multipart headers had already been committed. Neither endpoint turned an encoder exception into
a stated reason either, so a broken encoder surfaced as a 500 instead of the missing thing,
named.

Fix: one module-level helper, ``encode_or_reason(tap, frame)``, which never raises and returns
``(data, None)`` or ``(None, reason)``; both endpoints answer 503 with a plain-text reason
through it. The stream path probe-encodes the peeked frame once and discards it, on purpose:
that is what buys the promise that the stream will produce bytes.

### What a test could not have told us

TestClient answers ASGI in-process, and this project already paid once for trusting it: the whole
dashboard suite stayed green while production uvicorn refused every ``/ws`` upgrade. So the check
was run over real uvicorn and real HTTP, on three real servers:

- no encoder bound - stream and one-shot both ``503``, reason "no JPEG encoder is bound to the
  frame tap";
- encoder raising exactly as a missing cv2 does - both ``503``, reason "JPEG encoding failed:
  ModuleNotFoundError: No module named 'cv2'";
- working encoder, anti-vacuity - stream still ``200`` with
  ``multipart/x-mixed-replace; boundary=frame`` and JPEG magic in the first chunk; one-shot still
  ``200 image/jpeg`` with ``Cache-Control: no-store``.

Mutation proof: disabling the new guard makes the first case answer ``200`` and then send no bytes
within the 3 s read timeout - the defect reproduced end to end over the wire. Restored, the suite
is green: 455 passed. Commit ``96cc8e1``.

## Open questions

1. Window technology: app-mode window (recommended) vs plain browser tab vs native shell.
2. Does the camera preview need to work when capture is stopped (a "camera check" before starting)?
   Cheap to add in W2, but it changes the lifetime of the frame source.
3. Heartbeat staleness threshold (green→yellow). Proposed: yellow after ~2 s, red after ~5 s.
4. Should the window ship a screenshot in the README? The rendering is now proven, but the
   only capture in hand shows the author's face; publishing a personal photo is the owner's call.

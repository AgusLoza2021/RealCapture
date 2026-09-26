# The Control Room window

The control room is one dark window that answers two questions at a glance:
**is my camera working**, and **is the data reaching Blender**. It shows your
own face, the connection lights, and the live telemetry.

Blender is **not** needed to open the window. If Blender is closed, the window
still opens; the "Blender rig" light simply reads red.

## Opening it

Double-click `control-room.cmd` in the repository folder. It starts the capture
pipeline, waits until the window is actually answering, and only then opens it
in Edge's app mode, so it looks like its own window rather than a browser tab
(and you never land on a connection-refused page). Pressing a key in the
launcher window stops the capture. If Edge is not installed, the launcher says
so and opens an ordinary browser tab instead.

The manual equivalent, if you prefer a terminal:

    backend\.venv\Scripts\python backend\run_capture.py --engine mediapipe --camera 0 --dashboard 8765

then open <http://127.0.0.1:8765/> in any browser.

Options for the launcher:

- `--port 9000` - serve the window on a different port.
- `--camera 1` - use a different camera.
- `--no-browser` - start the capture but open nothing (used for testing).

## The four light states

Every connection card shows one of four words, as text as well as colour:

- **GREEN** - a fresh signal arrived within the last second or two. The reason
  line, if there is one, is good news.
- **YELLOW** - the connection exists but is degraded or stale, and the reason
  says what is wrong.
- **RED** - the signal is absent or failed, and the reason says which.
- **UNKNOWN** - the window has not heard anything about this connection yet.
  It is drawn as a hollow grey dot, deliberately unlike red: "not known yet"
  is not the same as "failed". Either way it is never green.

The one rule behind all four: **a light is never green because the data is
absent.** Silence is never mistaken for success. And a green light may still
carry a useful line - for example, that the rig is driving shape keys only
because the bone path was refused. That refusal is the safety gate working,
not a fault, so it belongs in the reason text, not in the colour.

## What you see, what it means, what to do

| What you see | What it means | What to do |
| --- | --- | --- |
| "Camera" not green | No fresh frame is arriving: the camera may be missing, already held by another program, or blocked. | Close other camera apps and restart the launcher; the capture window shows the exact error. |
| "Packets to Blender" not green | The capture is running, but the shape data is not reaching Blender. | Check the capture window for errors and restart the launcher; make sure nothing else is bound to the same UDP port. |
| "Blender rig" red, reason says Blender is not open | No heartbeat has ever arrived: Blender is closed or its addon is not running. | Start Blender with the addon listening; the light turns green by itself once data flows. |
| "Blender rig" yellow, reason says nothing is bound | Blender is open and answering, but no rig is bound, so nothing moves yet. | Run the addon's bind/wizard step inside Blender. |
| The camera image shows an overlay explaining that the stream stopped | The preview ended honestly instead of freezing on the last frame. | Read the reason on the overlay; usually the capture has stopped - restart the launcher. |

Two small promises baked into the window:

- The camera preview **stops** when frames stop arriving; it never freezes on
  the last frame, because a frozen face looks alive when it is not.
- The window needs only the Python virtualenv to run. **Blender is what makes
  the third light real**: without it the window works fine, and that light
  stays red until Blender joins.

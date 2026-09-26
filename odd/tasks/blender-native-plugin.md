# Blender-native plugin: the cockpit moves into Blender's sidebar

Feature: RealCapture installs into Blender as a native extension (4.2+) and the
whole capture can run from Blender's own UI. One button starts the camera
pipeline as a hidden child process, the sidebar shows the three connection
lights with their reasons, another button opens the Control Room window, and
the addon stops the pipeline when the capture is over. The two-app flow (a
`.cmd` launcher plus Blender) keeps working for anyone who prefers a terminal,
but it stops being the only path.

## Owner request

> "Me encantaria que esto sea un plugin de BLENDER de facil acceso para
> instalar y abrir, te ocupas? De esta manera lo ejecuto desde Blender."

## Decisions taken before the first write

1. **The pipeline stays a child process, not embedded.** The addon launches
   `backend/run_capture.py` with `backend/.venv/Scripts/python.exe`, hidden,
   reusing the MediaPipe path and the latency already proven (9.11 ms average,
   17.97 ms max, 29.98 fps). Embedding mediapipe + opencv inside Blender would
   cost roughly 80 MB of wheels, put capture on Blender's UI thread, and force
   a re-proof of everything already proven. The owner chose this option.
2. **The Control Room window stays.** It owns the live camera preview. The
   panel gets a button that opens it; the panel itself carries the lights.
3. **The live-session write freeze is lifted** by the owner (nothing is being
   tested right now), so this feature may edit `addon/ui.py`,
   `addon/__init__.py` and add new addon modules.

## Non-goals

- No new Python dependency in the addon: stdlib only (`subprocess`, `urllib`,
  `json`, `threading`, `os`, `pathlib`).
- No second traffic-light implementation: the panel renders the dashboard's own
  `connections` array.
- No wheel bundling and no mediapipe inside Blender's Python.
- No change to the proven consumer/bind path (52/52 shape keys, T10).

## Frozen contract (parent-owned; a writer must not invent around it)

1. **Entry point.** 3D Viewport > Sidebar (N) > RealCapture. Existing panels
   keep their content; the new controls are additive sections of the main
   panel. New operators are new `bl_idname`s (`realcapture.start_backend`,
   `realcapture.stop_backend`, `realcapture.open_control_room`); the existing
   `realcapture.start_capture` (the UDP consumer) keeps its semantics.
2. **Preferences** live in a new `addon/preferences.py`
   (`bpy.types.AddonPreferences`): `repo_root`, `python_executable` (default
   `<repo_root>/backend/.venv/Scripts/python.exe`), `udp_port` (11111),
   `dashboard_port` (8765), `camera_index` (0), `open_browser_on_start`
   (False). When the scene property `udp_port` and the preference disagree, the
   start operator refuses and names both values: it never picks one silently.
3. **The command line is built by a pure function** and passed to `Popen` as a
   list. `shell=True` is forbidden. `cwd` is `repo_root`; `stdin` is
   `DEVNULL`; stdout and stderr are appended to
   `<repo_root>/soak_output/backend.log` (that directory is already
   gitignored).
4. **Hidden start.** `creationflags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`
   on Windows. No console window may appear: this feature exists partly because
   the `.cmd` flow pops consoles.
5. **Stop is a tree kill** (`taskkill /PID <pid> /T /F`) followed by a bounded
   wait for the child to disappear. A stop that did not stop says so.
6. **Never a silent fallback.** An unset `repo_root`, a missing interpreter or
   a missing `run_capture.py` refuses with the exact missing path. Capability
   is never decided by a `PATH` probe.
7. **The lights are the dashboard's, verbatim.** The addon reads
   `GET http://127.0.0.1:<dashboard_port>/api/status` and renders its
   `connections: [{id, label, state, reason, detail}]`. The addon computes no
   threshold of its own; the single source of truth stays
   `backend/dashboard/status_model.py`.
8. **No network I/O on Blender's main thread.** The fetch runs on a daemon
   thread with a timeout; the UI timer only reads a cached snapshot. A hung
   server must never freeze Blender.
9. **Absence is never green.** No answer from the dashboard renders an explicit
   offline state carrying the reason (`connection refused`, timeout), and a
   snapshot older than a few seconds is labelled with its age instead of being
   shown as live.
10. **A child the addon did not start is never killed by the addon.** If
    something already answers on the dashboard port, the panel reports
    "already running, reusing" and the stop button stays honest about it.
11. **`unregister()` stops the child this addon started**, so disabling the
    addon cannot leave a camera running behind the user's back.
12. **One version, two declarations.** `blender_manifest.toml`'s `version`
    must equal `bl_info["version"]`, and its `name` must equal
    `bl_info["name"]`; a test pins both equalities.
13. **The package directory keeps its name.** The repository's `addon/`
    directory stays `addon/` (the dev-mode harness imports `addon.ui`). The
    extension build stages a copy under a directory named after the manifest
    `id`, so nothing in the repository is renamed. Build output goes to
    `dist/`, which becomes gitignored.
14. **License.** `license = ["SPDX:GPL-3.0-or-later"]` in the manifest, the
    same as the repository's `LICENSE`.

## Work units

### L1 - the launcher that started nothing (parent, inline, done)

`camera-to-rig.cmd` expanded `%PORT%` in the pipeline command and in the
Blender command, but never defined it. `cmd.exe` expands an undefined variable
to nothing, so the backend was invoked as `--port` with no value:

```
run_capture.py: error: argument --port: expected one argument
```

The pipeline window died on the spot. Blender still opened, the character still
loaded and the live harness fell back to its own default port - so the run
looked like a working run with nobody in front of the camera. On this machine a
gitignored `local.cmd` had been masking part of it; a fresh clone had nothing
to mask it. No test could catch it: nothing checked that launcher's exit code.

Fix and its barrier: `set "PORT=11111"` is now defined before the first use
(fixed on purpose so it always matches `backend/run_capture.py` and the addon's
`udp_port`), plus `tests/test_launcher_ports.py`, which asserts that a launcher
expanding `%PORT%` defines it first, that the value is a usable port, that
camera-to-rig's value equals `parse_args([]).port` from the backend itself, and
that the constant is actually expanded.

### P1 - packaging: manifest, staging build, the real validator, Blender loading it

Deliverable: `packaging/blender_manifest.toml` (source of truth),
`tools/build_extension.py` (stage `dist/<id>/` plus the manifest, then
optionally validate), `tests/test_extension_packaging.py` (version and name
parity with `bl_info`, no machine path inside the manifest), `dist/` added to
`.gitignore`, and the README install line.

Acceptance: Blender's own installed validator exits 0 on the staged directory
(`blender --command extension validate <staged>`, output pasted as evidence),
`blender --command extension build` produces a zip, that zip installs into an
isolated `BLENDER_USER_EXTENSIONS`, and a headless Blender run reports the
extension in `addon_utils.modules()`. The validator is the spec; the online
manifest documentation 404s.

### P2 - `addon/backend_process.py`: the launcher core, pure and bpy-free

Resolution (repo root, interpreter, script, log path), the argv builder, the
environment, the hidden-start flags, start / stop / is-alive, and an injected
prober for "something already answers on the dashboard port". Stdlib only, no
`bpy`, testable on the system Python.

Acceptance: focused tests, plus a mutation proof on the empty-value guard
(deleting the guard must fail a test).

### P3 - `addon/dashboard_client.py`: the status reader, pure and bpy-free

An injected fetcher, a defensive parse of `/api/status` (a missing or renamed
field renders an explicit unknown state, never green), and a cockpit model
distinguishing `offline(reason)` from `online(connections)` from
`stale(age_s)`. Stdlib only, testable on the system Python.

### P4 - the cockpit: `addon/preferences.py`, `addon/ui.py`, `addon/__init__.py`

Preferences, the new panel section (start / stop / open Control Room, the three
lights with their reasons and states as text as well as colour), the background
poller thread plus the `bpy.app.timers` tick, stop-on-unregister, and the
"already running, reusing" path.

Depends on P2 and P3: the UI is the thin layer, never the place where process
handling or threshold logic lives.

### P5 - docs and the README pin

`docs/install-blender-addon.md`, the README pointer, and the test-count pin.

### P6 - the parent's end-to-end proof

Build the zip, install it into an isolated extensions directory, then a
headless Blender run: start through the addon's own code path, observe the
child alive, the dashboard answering, the lights non-empty, stop, and observe
the child gone. Then the owner's own test with a real face.

## Evidence

- L1: the defect reproduced from the command line before the fix
  (`argument --port: expected one argument`), the fix verified by the new
  launcher test failing without the `set "PORT=11111"` line and passing with
  it.

## Open questions

- Should the panel offer to create `backend/.venv` when it is missing? Current
  answer: no. The addon never installs dependencies; it names the exact command
  from `backend/README.md`.
- Should the panel show the camera preview too, or only the lights with a
  button to the Control Room? The Control Room already owns the preview, and a
  second decoder inside Blender's UI thread is a risk with no benefit.

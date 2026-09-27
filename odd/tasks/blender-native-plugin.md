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
13. **The package directory keeps its name; the staged tree is flat.** The
    repository's `addon/` directory stays `addon/` (the dev-mode harness
    imports `addon.ui`), and nothing in the repository is renamed. The build
    stages a COPY of its contents FLAT next to the manifest
    (`dist/blender_manifest.toml` + `dist/__init__.py` + the modules). The
    nested `dist/<id>/` layout this contract demanded first is WRONG: Blender's
    own validator rejects it (`Error, file missing from add-on:
    __init__.py`), and Blender creates the `<id>/` directory itself at install
    time (`BLENDER_USER_EXTENSIONS/<repo>/<id>/`), which is exactly what keeps
    the package's relative imports working after the rename. Build output goes
    to `dist/`, which becomes gitignored.
14. **License.** `license = ["SPDX:GPL-3.0-or-later"]` in the manifest, the
    same as the repository's `LICENSE`.
15. **A child that dies inside the startup grace is reported dead, never
    announced as started.** `start_backend` waits up to ~0.25 s after `Popen`;
    if the child has already exited, the reason APPENDS `it exited immediately
    (exit code N); see the log: <path>` to the reason that already says whether
    the dashboard port was checked. The panel renders that reason verbatim, and
    it asks `is_alive()` before it calls anything running. A child that dies on
    its first line (broken venv, bad argument, occupied port) is the loudest
    failure of this feature; it must not leave a green-looking panel behind.
16. **Every refusal is a `BackendError` naming the offending value, including a
    wrong TYPE.** `fps="30"` arriving from a preference, an integer field, must
    not surface as a bare `TypeError` traceback in Blender's console.

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

### P1 - packaging: manifest, staging build, the real validator, Blender loading it (done)

Deliverable: `packaging/blender_manifest.toml` (source of truth),
`tools/build_extension.py` (stage the flat tree plus the manifest, then
optionally validate or build), `tests/test_extension_packaging.py` (version and
name parity with `bl_info`, the GPL-3.0-or-later SPDX id, the staged layout, no
absolute `import addon` inside the package, `dist` gitignored, no machine path
inside shipped files), `dist` added to `.gitignore`, and the README test-count
pin.

Acceptance: Blender's own installed validator exits 0 on the staged directory
(output pasted as evidence), `blender --command extension build` produces a
zip, that zip installs into an isolated `BLENDER_USER_EXTENSIONS`, and a
headless Blender run loads the extension. The validator is the spec; the online
manifest documentation 404s.

**Contract amendment, from Blender's own tooling.** The acceptance criteria
above replaced `addon_utils.modules()` with the import + enable path, and rule
13's nested `dist/<id>/` staging with the flat one, because the nested layout
is not a layout Blender accepts: `validate` fails it with `Error, file missing
from add-on: __init__.py`, and the `<id>/` directory is created by Blender at
install time.

**Acceptance, reproduced by the parent** (not taken from the writer's report):

- `blender --command extension validate --valid-tags="" dist` ->
  `Success parsing TOML in "dist"`, exit 0.
- `blender --command extension build --source-dir dist --output-dir dist
  --valid-tags=""` -> `created: "dist\realcapture-0.1.0.zip", 45808`, exit 0.
  The zip's entries sit at its ROOT (`blender_manifest.toml`, the modules,
  `rigprofile/`, `presets/`), which is what Blender extracts into
  `<repo>/<id>/`.
- `blender --command extension install-file dist/realcapture-0.1.0.zip --repo
  user_default --enable` against an isolated `BLENDER_USER_EXTENSIONS` -> exit
  0, and the tree that appears is
  `<ext>/user_default/realcapture/{blender_manifest.toml,__init__.py,...}`;
  `--command extension list` reports `realcapture [installed]: "RealCapture"`.
- Headless Blender in the same isolated environment:
  `importlib.import_module("bl_ext.user_default.realcapture")` -> `IMPORT OK`
  with `bl_info` intact; `bpy.ops.preferences.addon_enable(module=...)` ->
  `ENABLED: True`; `RC_PT_main_panel` and `RC_PT_rig_connector_panel`
  registered; `dir(bpy.ops.realcapture)` = `bind_rig, load_profile,
  replay_session, scan_rig, start_capture, stop_capture, unbind_rig`;
  `addon_disable` -> `DISABLED: True`; exit 0.
- Mutation proofs, in the parent's hands: manifest `version` `0.1.0` -> `9.9.9`
  fails `test_manifest_version_matches_bl_info`; a temporary
  `addon/_zz_probe_import.py` containing `import addon` fails
  `test_staged_package_has_no_absolute_addon_imports`. Both restored -> 8
  passed.
- Canonical suite after the README pin moved 402 -> 410: `410 passed,
  1 warning`.
- Checked and accepted, not fixed: a top-level `packaging/` directory could
  shadow the PyPI `packaging` module as a namespace package, but a regular
  package found later on `sys.path` wins, and the measurement confirms it
  (`python -c "import packaging"` from the repo root resolves to
  site-packages). Nothing in this repository imports `packaging`.

### P2 - `addon/backend_process.py`: the launcher core, pure and bpy-free (done)

Resolution (repo root, interpreter, script, log path), the argv builder, the
environment, the hidden-start flags, start / stop / is-alive, and an injected
prober for "something already answers on the dashboard port". Stdlib only, no
`bpy`, testable on the system Python.

Acceptance: focused tests, plus a mutation proof on the empty-value guard
(deleting the guard must fail a test).

**Contract amendment, from this delivery.** Two rules were added while P2 was
under review (15 and 16 above): the argv builder refuses a wrong TYPE, not only
an out-of-range value, and `start_backend` now reports a child that died inside
a short startup grace with its exit code and its log path instead of returning
`started=True` alone. Both were gaps in the parent's own contract, found by
reading the delivery.

**Checked and answered, not changed:** `build_argv` refuses
`dashboard_port == 0` because 0 is the backend's "dashboard off" switch and a
cockpit that cannot read a dashboard has no lights to draw.

### P3 - `addon/dashboard_client.py`: the status reader, pure and bpy-free (done)

An injected fetcher, a defensive parse of `/api/status` (a missing or renamed
field renders an explicit unknown state, never green), and a cockpit model
distinguishing `offline(reason)` from `online(connections)` from
`stale(age_s)`. Stdlib only, testable on the system Python.

**Checked and answered, not changed:** a failed poll keeps the last good
`fetched_at` and the same `connections` array, with `error` set, so the panel
can render live data with the age of the data it is still showing;
`fetched_at == 0.0` means "no successful read yet" and must never be rendered
as an age.

### P4 - the cockpit: `addon/preferences.py`, `addon/ui.py`, `addon/__init__.py` (done)

Preferences, the new panel section (start / stop / open Control Room, the three
lights with their reasons and states as text as well as colour), the background
poller thread plus the `bpy.app.timers` tick, stop-on-unregister, and the
"already running, reusing" path.

Depends on P2 and P3: the UI is the thin layer, never the place where process
handling or threshold logic lives.

**Measured against this machine's Blender before writing the interface:**

- `bpy.ops.wm.url_open` exists -> the Control Room button needs no browser
  probing code.
- `bpy.app.timers` exists -> the redraw tick is a timer, not a thread touching
  the UI.
- The preferences key for an installed extension is the FULL module path:
  after `addon_enable`, `bpy.context.preferences.addons` holds
  `bl_ext.user_default.realcapture`, and its `.preferences` is `None` while no
  `AddonPreferences` class is registered. So `bl_idname = __package__` is the
  correct idiom in both modes (dev `addon`, installed
  `bl_ext.user_default.realcapture`), and the panel must draw a sane section
  when `.preferences` is `None` instead of raising.

**Frozen interface.** A new pure module `addon/cockpit.py` (stdlib only, no
`bpy`, imports `backend_process` and `dashboard_client`) owns every decision;
`addon/ui.py` only draws. `addon/preferences.py` holds the `AddonPreferences`
class and nothing else.

`addon/cockpit.py`:

- Constants `DEFAULT_PYTHON_RELATIVE = "backend/.venv/Scripts/python.exe"`,
  `DEFAULT_SCRIPT_RELATIVE = "backend/run_capture.py"`, `DEFAULT_UDP_PORT =
  11111`, `DEFAULT_DASHBOARD_PORT = 8765`, `DEFAULT_CAMERA_INDEX = 0`.
- `class CockpitError(ValueError)`.
- `@dataclass(frozen=True) class PipelineSettings` with `repo_root: str`,
  `python_executable: str = ""` (empty means "derive it"), `udp_port: int =
  DEFAULT_UDP_PORT`, `dashboard_port: int = DEFAULT_DASHBOARD_PORT`,
  `camera_index: int = DEFAULT_CAMERA_INDEX`, `open_browser_on_start: bool =
  False`; methods `paths() -> BackendPaths` and `argv() -> list[str]` that
  delegate to `backend_process`, so the panel never builds a command line.
- `settings_from_preferences(prefs: Any, *, scene_udp_port: int | None = None)
  -> PipelineSettings`: reads the six preference fields (missing attributes are
  a `CockpitError` naming the attribute, never a silent default); an empty
  `repo_root` refuses naming the preference field; and when `scene_udp_port` is
  not `None` and differs from the preference, it REFUSES naming BOTH values
  (rule 2), because the addon's UDP consumer and the backend must agree.
- `HealthRow = NamedTuple(state, label, detail, icon)` with `state` one of
  `"green" | "yellow" | "red" | "unknown"`; `light_icon(state)` maps that to a
  Blender icon name (`CHECKMARK`, `ERROR`, `QUESTION`).
- `child_rows(process: BackendProcess | None) -> tuple[HealthRow, ...]`: one
  row, label `Backend`, state green while `is_alive()`, red otherwise, detail
  the process `reason` verbatim (so `exited immediately (exit code 3); see the
  log: <path>` reaches the user), empty state `unknown` with "not started" when
  there is no process.
- `connection_rows(snapshot: Snapshot, *, now_s: float) -> tuple[HealthRow,
  ...]`: the dashboard's own `connections` array, verbatim, one row each,
  `label` = the dashboard's `label`, `detail` = its `reason`; every row also
  carries the AGE of the snapshot. An empty array with an `error` renders ONE
  red row naming the error; an empty array with no error renders ONE unknown
  row saying the dashboard reported no connections. Absence is never green
  (rule 9).
- `next_tick_interval(poller_alive: bool) -> float | None`: `None` stops the
  timer; otherwise the redraw interval, so the timer's own decision is pure and
  testable.

`addon/preferences.py`: `class RealCapturePreferences(bpy.types.AddonPreferences)`
with `bl_idname = __package__`, fields exactly `repo_root: StringProperty`,
`python_executable: StringProperty`, `udp_port: IntProperty(11111)`,
`dashboard_port: IntProperty(8765)`, `camera_index: IntProperty(0)`,
`open_browser_on_start: BoolProperty(False)`, and
`register()`/`unregister()`.

`addon/ui.py`: `RC_OT_start_backend` (`realcapture.start_backend`),
`RC_OT_stop_backend` (`realcapture.stop_backend`), `RC_OT_open_control_room`
(`realcapture.open_control_room`), a `Pipeline` box added to
`RC_PT_main_panel.draw` with the three buttons and the rendered
`HealthRow` labels with their icons, a module-level `_process` / `_poller`, a
`_tick` timer callback that is exception-safe (Blender silently unregisters a
raising timer and the panel freezes) and returns
`cockpit.next_tick_interval(...)`, and a `register()`/`unregister()` pair that
starts and removes the timer. `unregister()` stops the poller and stops the
child this addon started (rule 11). Starting twice must report
"already running (pid N)" instead of starting a second child. Nothing on the
main thread performs network I/O (rule 8).

`addon/__init__.py`: register `properties`, then `preferences` (before `ui`,
which reads them), then `wizard`, then `ui`; unregister in reverse. The
`bl_info` dict is untouched.

Gates: `tests/test_cockpit.py` (pure: the refusal naming both ports, the
verbatim rows, the age text, the offline/unknown rows, the tick interval) and
`tests/test_plugin_wiring.py` (structural, because `bpy` cannot be imported
here: the three new `bl_idname`s exist and are unique, every pre-existing
`bl_idname` is preserved, `unregister` stops the child, `_tick` guards itself
with `try`/`except`, and `__init__.register` registers `preferences` before
`ui`).

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
- P2/P3, reproduced by the parent in its own hands (the writer's report was
  not taken as evidence):
  - `python -m pytest tests/test_backend_process.py
    tests/test_dashboard_client.py -q` -> `69 passed` (37 + 32).
  - Neither module imports `bpy` (docstring mentions only); the only
    non-stdlib import is `dashboard_client` importing the probe constants from
    `backend_process`.
  - Five mutations, each breaking exactly one gate and each restored
    byte-identically: a `shutil.which("python")` fallback for the missing venv
    interpreter -> `test_resolve_paths_missing_interpreter_names_venv_path_no_
    path_fallback`; `parse_status` reversing the dashboard's array ->
    `test_parse_status_returns_connections_verbatim`; a failed poll stamping
    `fetched_at` as if it were live data -> two poller gates; the startup grace
    disabled -> `test_start_backend_reports_a_child_that_died_inside_the_grace`;
    `fps` back to a bare comparison -> the wrong-type gate. The two
    parent-owned amendments were mutation-proved the same way.
  - The real child contract was observed through a `popen_factory` recorder
    that delegates to the real `subprocess.Popen`: `creationflags ==
    CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` on Windows, the log appended
    in the log directory, and a stop that kills only the tree it started.
  - A live measurement of the grace reason, from a real child that exits 3:
    `backend started (pid 28192); dashboard port None was not checked; it exited
    immediately (exit code 3); see the log: <log_path>`.
  - Canonical suite after the README pin moved 410 -> 479: `479 passed,
    1 warning`.

- P4: delivered by a worker (two new modules, two test files, the wired panel),
  then read line by line by the parent, which found four real defects:
  - D3: the stop operator cleared `_process` even when the stop FAILED, so the
    panel would have reported "not started" while the child was still alive.
    Fixed with the pure `cockpit.stop_clears_state(result)`.
  - D4: `_ensure_poller` ignored a `dashboard_port` change, so the poller kept
    reading the old port - stale by construction. Fixed with the pure
    `cockpit.needs_new_poller(current_port, wanted_port)`.
  - D8: `RealCapturePreferences` had no `draw()`, so the class was invisible in
    Blender's UI and the owner could not set `repo_root` - a blocker for "run it
    from Blender". Fixed by rendering all six fields.
  - D9 (found only by RUNNING the panel): `_draw_pipeline` was decorated
    `@staticmethod` while its body called `self._draw_health_row(...)`, so the
    first draw by a human raised `NameError`. pytest never draws, so no test
    could see it. Fixed by dropping the decorator, and closed as a class with a
    structural gate (`test_no_staticmethod_uses_self`) that rejects any
    `@staticmethod` whose body reads `self`.
- P4 live evidence, from the installed extension in Blender 4.5.2 (isolated
  `BLENDER_USER_EXTENSIONS`), not from pytest:
  - `addon_enable` -> `{'FINISHED'}`; preferences present with all six fields
    and their defaults (`''`, `11111`, `8765`, `0`, `False`); `draw` present.
  - the four operators exist and the pre-existing `start_capture` survives.
  - `bpy.app.timers.is_registered(ui._tick)` is True after enable and False
    after disable; `_poller`, `_poller_port` and `_process` are all cleared by
    `unregister`, with no poller thread left alive.
  - the poller is reused on the same port, rebuilt on a port change, and the
    rebuilt-away poller is stopped (`is_alive()` False).
  - three refusals reach the user as an error report naming the offender: the
    scene/preference port disagreement (both values), an empty `repo_root`, and
    a `repo_root` that does not exist; a stop with nothing started returns
    `{'CANCELLED'}`.
  - the panel body was rendered through Blender's own code path with a
    recording layout, for four states: nothing started ("Dashboard: not
    polling", "Backend: unknown / not started"), a retained green row
    downgraded to yellow while `snapshot.error` is set, a healthy row, and a
    dashboard that never answered ("Dashboard: red / timeout after 1.5 s" -
    absence is never green).
- P4 mutations, each breaking exactly one gate and each restored
  byte-identically: `stop_clears_state` always clearing ->
  `test_stop_clears_state_only_after_a_real_stop`; `needs_new_poller` ignoring
  the port -> `test_needs_new_poller`; `draw()` dropping `repo_root` -> the
  frozen-field gate; the stop operator clearing `_process` unconditionally ->
  `test_stop_operator_obeys_the_pure_decision`; the `@staticmethod` restored ->
  `test_no_staticmethod_uses_self`.
- Canonical suite after the README pin moved 479 -> 524: `524 passed,
  1 warning`.

## Open questions

- Should the panel offer to create `backend/.venv` when it is missing? Current
  answer: no. The addon never installs dependencies; it names the exact command
  from `backend/README.md`.
- Should the panel show the camera preview too, or only the lights with a
  button to the Control Room? The Control Room already owns the preview, and a
  second decoder inside Blender's UI thread is a risk with no benefit.

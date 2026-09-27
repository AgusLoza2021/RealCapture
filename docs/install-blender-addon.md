# Install RealCapture as a Blender add-on

This guide is for running RealCapture **from inside Blender**, with no console window and no
`.cmd` launchers. The add-on is a normal Blender extension: it starts and stops the capture
backend as a hidden child process and shows the state of the whole chain in the 3D Viewport
sidebar. The Control Room window still exists — the panel has a button that opens it.

Prerequisite: **Blender 4.2 or newer**. The declared floor is `4.2.0` in
`packaging/blender_manifest.toml`; Blender refuses to install the add-on on anything older.

## 1. Build the extension zip

```bat
python tools/build_extension.py --build --blender "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
```

The output is `dist/realcapture-0.1.0.zip` (gitignored). The build stages the manifest and the
add-on modules **flat** at the root of the source tree, because that is the layout Blender's
own extension tooling validates and installs; Blender creates the package directory itself.
`tools/build_extension.py` needs `--blender` (or `blender` on `PATH`) and says so if it cannot
find one.

To validate without installing:

```bat
blender --command extension validate --valid-tags="" dist
```

## 2. Install it

From a terminal — this is the path this project verified end to end:

```bat
blender --command extension install-file "dist\realcapture-0.1.0.zip" --repo user_default --enable
```

Or from Blender's UI: **Edit ▸ Preferences ▸ Add-ons ▸ (top-right ▾) ▸ Install from Disk…**
and pick the zip. Blender routes a package that contains a manifest to its extension installer
and enables it.

Installed extensions land in your user extensions directory and the add-on's module path
becomes `bl_ext.user_default.realcapture`. That matters only when reading a traceback.

## 3. Set one preference

**Edit ▸ Preferences ▸ Add-ons ▸ RealCapture ▸ Preferences** shows six fields:

| Field | Default | What it is |
|---|---|---|
| `repo_root` | *(empty)* | **The only required field**: the folder where you cloned RealCapture. |
| `python_executable` | `<repo_root>/backend/.venv/Scripts/python.exe` | The interpreter that runs the backend. Leave empty to use the venv. |
| `udp_port` | `11111` | The UDP port the packets travel on. Must match the scene's `udp_port`. |
| `dashboard_port` | `8765` | The Control Room / dashboard port. |
| `camera_index` | `0` | Webcam index, as OpenCV numbers them. |
| `open_browser_on_start` | off | Open the Control Room automatically when the pipeline starts. |

Before the first start, create the backend virtual environment as described in
[`backend/README.md`](../backend/README.md) — the add-on never installs dependencies for you,
it only tells you what is missing.

## 4. Use the panel

Open the **3D Viewport**, press **N**, and pick the **RealCapture** tab. The panel shows:

- **Start** — launches the backend as a hidden child process (no console window) and starts
  polling the dashboard. The child's output is appended to
  `<repo_root>/soak_output/backend.log`.
- **Stop** — stops the child process tree.
- **Control Room** — opens `http://127.0.0.1:<dashboard_port>` in your default browser.
- The three lights — **camera**, **packets**, **Blender** — with their state written as text
  next to the colour, each with the reason the light is not green.

The lights come from the dashboard's own status endpoint: the add-on draws what the dashboard
reports and computes no threshold of its own. A dashboard that has never answered reads red
with the read error, never green.

## Refusals are explicit

Start fails loudly, naming the offender, instead of guessing:

| Situation | What you see |
|---|---|
| `repo_root` is empty | `the RealCapture preference 'repo_root' is empty: set the RealCapture repository folder in the add-on preferences` |
| `repo_root` does not exist | `RealCapture repository does not exist or is not a directory: <path>` |
| The venv interpreter is missing | The exact path it looked for; there is no fallback to whatever `python` is on `PATH`. |
| The scene's `udp_port` differs from the preference | `UDP port disagreement: the scene uses udp_port=… but the add-on preference uses udp_port=…; they must agree before the backend starts` |
| Start, while a dashboard or a stranger already holds the port | It says so and refuses to start a second child. |

## What the add-on does not do

- It never kills a process it did not start. If a backend was already running, the add-on
  reports it and reuses it.
- It never installs Python dependencies.
- It never touches `bpy` from a background thread: the poller thread only performs HTTP reads,
  and every scene access happens on Blender's main thread via a `bpy.app.timers` tick.
- MPFB2 is a **separate, optional runtime dependency** for the character/rig side. Depending
  on GPL software does not relicense this project.

Disabling the add-on or quitting Blender stops the child the add-on started, stops the poller
thread, and removes its timer.

## License

The add-on is **GPL-3.0-or-later**. This is not a free choice: Blender's add-on platform
requires GPL-compatible licensing, and this project publishes everything under that same
license. See [`LICENSE`](../LICENSE) and
[`docs/realcapture-tdd.md`](realcapture-tdd.md) for the reasoning.

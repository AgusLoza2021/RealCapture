# RealCapture

Real-time facial expression capture for Blender. A standard RGB webcam drives a character's
facial rig live, instead of keyframing every expression. Recording and bake follow later in
the roadmap.

**Status:** pre-release, in active development. Windows-first, Blender 4.2 LTS floor.
Authoritative milestone status lives in [`docs/roadmap.md`](docs/roadmap.md) — this file does
not restate it, on purpose.

## The Control Room: watch the whole chain live

Double-click `control-room.cmd` and a live window opens — your camera preview plus three
connection lights (**camera**, **packets**, **Blender**) — without touching any code. The
whole point of RealCapture is that you can always see the state of the chain, so the window
opens in browser app mode and reads like an instrument panel, not a web page:

- **Camera** — is a fresh webcam frame arriving?
- **Packets to Blender** — is the capture actually sending shape data?
- **Blender rig** — is the character in Blender receiving and applying it?

A light is never green because data is absent: when something is wrong, the light's reason
line says what. Blender does not need to be open — its light simply reads red with that
reason until Blender joins. See [`docs/control-room.md`](docs/control-room.md).

## Design pillars

1. **Capture is commodity; mapping is the product.** Capture engines are pluggable
   open-source backends; the differentiation lives in the mapping layer.
2. **Blender-safe concurrency.** No threads touch `bpy`. Every scene write happens on the
   main thread.
3. **Local-first, open source.** Windows-first and local-first by design; the entire
   repository is public and GPL-3.0-or-later.

## How it fits together

Two processes and one narrow seam:

```
capture backend (Python, external)  ──UDP/JSON──▶  Blender addon (main thread)
MediaPipe or OpenSeeFace                            receiver → consumer → mapping layer → rig
```

The packet schema is the stable public seam between the capture backends and any consumer —
the Blender addon, the Control Room dashboard, or a tool you write yourself. It is versioned
and mirrored byte-identically on both sides (`backend/common/packets.py` and
`addon/schema.py`), pinned by `tests/test_schema_sync.py`.

## Prerequisites

| Prerequisite | Check | Where to get it | If it is missing |
|---|---|---|---|
| Blender 4.2 LTS or newer | `blender --version` in a terminal | [blender.org/download](https://www.blender.org/download/) | The demo launchers fail fast with an explicit error; the addon never installs on an older Blender (its floor is declared as 4.2.0). |
| Python 3.11 (capture backend) | `python --version` | [python.org/downloads](https://www.python.org/downloads/) | The backend cannot start; the Control Room's camera and packet lights stay red and their reason lines say the pipeline is down. |
| A standard RGB webcam | Any built-in or USB camera visible to Windows | Usually built in; any USB webcam | MediaPipe detects no face and the backend sends no packets at all — the Blender window looks frozen, which is the pipeline working, not a hang. |
| MPFB2 (optional) | Only needed to create the demo character `.blend` once, inside Blender | [MPFB2 releases](https://github.com/makehumancommunity/mpfb2) | Everything except the generated-character demo works without it; the character demo fails fast with a message naming the missing `.blend`. |

The design rule behind that last column: **a broken light must say why instead of looking
green.** Every failure above surfaces as an explicit error or as a red/yellow light with a
reason — never as a silent success.

## Environment variables (optional overrides)

The launchers read three environment variables so that nothing machine-specific lives in
published code:

| Variable | Meaning | Default when unset |
|---|---|---|
| `RC_MPFB_ROOT` | Root folder of an isolated Blender + MPFB2 environment | `%LOCALAPPDATA%\RealCapture\mpfb` |
| `RC_BLENDER` | Full path to `blender.exe` | Discovered automatically (PATH, then the standard install folders) |
| `RC_CHARACTER` | Full path to the character `.blend` | `%RC_MPFB_ROOT%\tmp\character.blend` |

**`local.cmd`** — optionally create this file next to the launchers at the repository root
(it is gitignored) and put your machine's values in it:

```bat
set "RC_MPFB_ROOT=D:\blender-mpfb"
set "RC_BLENDER=C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
set "RC_CHARACTER=D:\rigs\my_character.blend"
```

The launchers source `local.cmd` if it is present, so a stranger can run the demo on another
machine without editing a single published file.

## Setup

The capture backend runs as an external process and needs the media stack; see
[`backend/README.md`](backend/README.md) for its virtualenv and dependency setup. The Blender
addon needs no dependencies beyond Blender itself; see [`addon/README.md`](addon/README.md)
for install and quick start.

## Camera to rig (the demo you can watch)

Double-click `camera-to-rig.cmd` and sit in front of the camera: the pipeline in one window drives
a real MPFB2 character in Blender with the same consumer path the addon uses.

```bat
camera-to-rig.cmd          :: camera 0
camera-to-rig.cmd 1        :: camera 1
```

It needs two things that are **not** in the repository: a camera, and a character `.blend`
created once in Blender with MPFB2 installed. There is no committed generator script — build
the character once inside Blender with MPFB2, save it as a `.blend`, and point `RC_CHARACTER`
at it (or leave it unset and place the file at the `RC_MPFB_ROOT` default path shown above).

With nothing in front of the camera, MediaPipe detects no face and the backend sends no packets
at all, so the Blender window looks frozen — that is the pipeline working, not a hang.

For a real character the bind reports that it bound **shape keys only**, and refuses the
point/bone path. That is deliberate: the character's bone named `head` sits at chest height, so
driving anchors from it tore the mesh by 0.82 m. The gate measures the bind's own at-rest damage
and reverts it; see `addon/rigprofile/headbone.py`.

To just watch the chain without opening Blender, use the Control Room (top of this page).

Headless equivalents (no camera, no display):

```bash
# Inject one packet through the real consumer path and assert a named shape key moved.
blender -b --python tools/blender_mpfb_live.py -- --self-test

# Bounded headless run of the real UDP receive path: exits 0 when packets arrived.
blender -b --python tools/blender_mpfb_live.py -- --seconds 20
```

## Headless checks

```bash
# Unit and integration tests. Plain Python 3.11; the capture engines are not required,
# because heavy imports are guarded.
python -m pytest tests/ -q

# End-to-end addon smoke test: builds a synthetic rig, runs the wizard, drives packets,
# and verifies face-point movement through the depsgraph.
blender -b --python tools/blender_smoke_test.py

# Transport soak test. Start the sender first: the pump runs for the full duration and
# does not wait for the first packet. Blender needs roughly 15 s to build its scene.
python tools/soak_send.py --minutes 3 --hz 30 --port 11111 &
blender -b --python tools/blender_soak.py -- 2 11111
```

The soak run exits non-zero when a quality gate fails: too few applied packets, invalid or
lost packets, or transport latency above 100 ms measured over the whole session. Latency is
compared across two clocks on purpose — the sender's epoch-millisecond stamp against the
receiver's wall clock — so a receiver-side clamping bug cannot present as a perfect result.
`tools/soak_send.py --stamp-skew-ms` injects a known offset as a positive control for that
measurement.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | Capture engines (MediaPipe default, OpenSeeFace alternative), packet schema, Control Room dashboard, CLI entry point |
| `addon/` | Blender addon: receiver, consumer, telemetry, session record/replay, rig connector, wizard, UI panel |
| `tools/` | Headless Blender smoke and soak tests, the soak sender, and the pure soak gate logic |
| `tests/` | pytest suite (388 tests) |
| `docs/` | Technical design, milestone roadmap, Control Room guide, landscape research |
| `odd/` | Feature task documents and their evidence |

## Scope and IP boundary

RealCapture is fully open source under GPL-3.0-or-later: every file in this repository —
including the mapping layer (`addon/rigprofile/`, `addon/binding.py`), the capture backends,
and the test suite — is published under that license. There is no private half.

The one deliberately stable seam is the **transport packet schema** (`backend/common/packets.py`,
mirrored in `addon/schema.py`): capture backends emit it, any consumer can parse it, and it is
versioned so the two sides can evolve together. See §2 of
[`docs/realcapture-tdd.md`](docs/realcapture-tdd.md) for the licensing details.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE). RealCapture is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any later version.

Why GPL: RealCapture calls the Blender Python API (`bpy`), and any published script that does
so must be GPL; the Blender Extensions Platform additionally accepts only GPL-3.0-or-later
add-ons. GPL-3.0-or-later is the license that keeps the project free, shareable, and
publishable on the Extensions Platform.

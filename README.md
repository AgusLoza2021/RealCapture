# RealCapture

Real-time facial expression capture for Blender. A standard RGB webcam drives a character's
facial rig live, instead of keyframing every expression. Recording and bake follow later in
the roadmap.

**Status:** pre-release, in active development. Windows-first, Blender 4.2 LTS floor.
Authoritative milestone status lives in [`docs/roadmap.md`](docs/roadmap.md) — this file does
not restate it, on purpose.

## Design pillars

1. **Capture is commodity; mapping is the product.** Capture engines are pluggable
   open-source backends; the differentiation lives in the mapping layer.
2. **Blender-safe concurrency.** No threads touch `bpy`. Every scene write happens on the
   main thread.
3. **Local-first, open later.** Windows-first for the local phase; the open-source release
   comes after production quality.

## How it fits together

Two processes and one narrow seam:

```
capture backend (Python, external)  ──UDP/JSON──▶  Blender addon (main thread)
MediaPipe or OpenSeeFace                            receiver → consumer → mapping layer → rig
```

The packet schema is the public seam between the open capture ecosystem and the private
mapping engine. It is versioned and mirrored byte-identically on both sides
(`backend/common/packets.py` and `addon/schema.py`), pinned by `tests/test_schema_sync.py`.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | Capture engines (MediaPipe default, OpenSeeFace alternative), packet schema, dashboard, CLI entry point |
| `addon/` | Blender addon: receiver, consumer, telemetry, session record/replay, rig connector, wizard, UI panel |
| `tools/` | Headless Blender smoke and soak tests, the soak sender, and the pure soak gate logic |
| `tests/` | pytest suite (158 tests) |
| `docs/` | Technical design, milestone roadmap, landscape research |
| `odd/` | Feature task documents and their evidence |

## Setup

The capture backend runs as an external process and needs the media stack; see
[`backend/README.md`](backend/README.md) for its virtualenv and dependency setup. The Blender
addon needs no dependencies beyond Blender itself; see [`addon/README.md`](addon/README.md)
for install and quick start.

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

## Scope and IP boundary

Public documents describe the mapping layer's **interface**, never its internals. The mapping
layer — calibration model, expression solver logic, rig-profile system, correctives strategy —
is private methodology. See §2 of [`docs/realcapture-tdd.md`](docs/realcapture-tdd.md) for the
full boundary.

## License

None declared yet. The repository is not published, and licensing is decided during the
open-source preparation milestone.

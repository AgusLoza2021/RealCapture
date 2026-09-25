# RealCapture — Technical Design Document

Real-time facial expression capture for Blender: webcam input → expression data → rig mapping → live character animation, with recording and bake.

**Status:** Draft v0.1 (M0)
**Audience:** Public-facing design doc. Private methodology and the custom mapping solver are intentionally excluded (see §2 IP Boundary).

---

## 1. Overview

RealCapture drives a 3D character's facial rig inside Blender from a standard webcam in real time, eliminating per-expression keyframing. It is built as a **composition of proven open components plus a private mapping layer**:

```
┌──────────────────────┐    ┌─────────────┐    ┌───────────────────────────┐
│  Capture backend     │    │  Transport  │    │  Blender addon            │
│  (external process)  │───▶│  UDP/JSON   │───▶│  consumer (main thread)   │
│  MediaPipe or        │    │  or OSC     │    │  latest-frame-wins        │
│  OpenSeeFace         │    └─────────────┘    └────────────┬──────────────┘
└──────────────────────┘                                    │
                                              ┌─────────────▼──────────────┐
                                              │  Mapping layer (private)   │
                                              │  calibration · solver ·    │
                                              │  rig profiles · correctives│
                                              └─────────────┬──────────────┘
                                                            ▼
                                               character rig (live + bake)
```

### Design pillars
1. **Capture is commodity; mapping is the product.** Capture engines are pluggable open-source backends. All differentiation lives in the mapping layer.
2. **Blender-safe concurrency.** No threads touching `bpy`. All Blender writes happen on the main thread.
3. **Local-first, open later.** Windows-first for the local phase; open-source release comes after production quality.
4. **Reviewable work units.** Every milestone ships in small, independently reviewable slices.

---

## 2. IP Boundary

- The capture backends (MediaPipe, OpenSeeFace) are used under their open licenses, unmodified where possible.
- The **mapping layer** — calibration model, expression solver logic, rig-profile system, correctives strategy — is private methodology. Public documents describe its *interface*, never its internals.
- The transport packet schema (§5) is public and stable: it is the seam between the open ecosystem and the private engine.

## 3. Users & Target Platforms

| Decision | Value |
|---|---|
| Primary user | Solo technical artist / animator (the project author) |
| Phase-1 OS | **Windows** |
| Later | macOS/Linux evaluated before open-source release |
| Blender floor | **4.2 LTS** |
| Capture hardware | Standard RGB webcam (external cameras supported via index) |

## 4. Capture Backends

Both backends are supported behind a common backend interface. Selection is a user setting, not an architectural fork.

### 4.1 MediaPipe Face Landmarker (default)
- License: Apache-2.0. Models (`.task`) redistributable.
- Output: 478 landmarks, **52 ARKit-shaped blendshape scores**, facial transformation matrix (head pose).
- Strengths: expression coverage out of the box; the ARKit-52 set is the industry interchange format.

### 4.2 OpenSeeFace (alternative)
- License: BSD-2-Clause. Ships own ONNX models; designed to run as an external process streaming UDP.
- Output: quasi-3D landmarks, head pose, optional per-user calibrated expressions.
- Strengths: 30–60 fps on CPU; **more robust than MediaPipe in low light, noise, and wide head-pose ranges**; better mouth-pose range representation.

### Backend interface (public)
Each backend produces, per frame:

```json
{
  "t": 1718345678901,
  "engine": "mediapipe",
  "conf": 0.97,
  "pose": { "rx": 0.0, "ry": 12.5, "rz": -3.2, "tx": 0.1, "ty": -0.05, "tz": 0.0 },
  "shapes": { "eyeBlinkLeft": 0.42, "jawOpen": 0.18, "...": "ARKit-52 or backend-native" },
  "extra": {}
}
```

- `shapes` are normalized to a backend-agnostic semantic channel set on the Blender side; backends may emit ARKit-52 or native channels.
- The schema is versioned; `extra` carries backend-specific fields.

## 5. Transport

- **UDP/JSON** for the local phase (simple, zero-dependency, proven by OpenSeeFace's own design).
- **OSC** (VTuber ecosystem / VMC compatibility) evaluated for the open-source phase.
- Semantics: **latest-frame-wins**. The receiver drains the socket queue and applies only the newest packet. Stale facial frames are worse than dropped frames.

## 6. Blender Integration (constraints & rules)

These rules come from Blender's documented constraints and community-validated practice:

1. **No Python threads touching `bpy`** — documented as unsupported and crash-prone. Capture runs in a separate OS process.
2. **Consumer loop**: non-blocking socket drained inside `bpy.app.timers` at 30–60 Hz on the main thread.
3. **Apply path**: latest packet → custom properties on one controller object → **native Blender drivers** → shape keys / bones. No Python driver expressions.
4. **Epsilon gating**: skip depsgraph work when values change less than a threshold.
5. **Preview vs Record separation**: preview writes properties only; recording samples at a fixed FPS and inserts keyframes in batches (never one keyframe per packet).
6. **Viewport budget**: document recommended Simplify settings; per-stage latency telemetry makes viewport cost visible.

### Latency budget (per stage, measured end-to-end)
| Stage | Budget |
|---|---|
| Camera + inference | ≤ 25 ms |
| Transport (localhost) | ≤ 1 ms |
| Blender consume + apply | ≤ 8 ms (one 120 Hz tick) |
| Viewport evaluation | scene-dependent, measured and reported |
| **End-to-end target** | **≤ 60 ms**, hard alert above 100 ms |

## 7. Mapping Layer (public interface only)

The mapping layer is RealCapture's core value. Its public interface:

- **Input**: backend-agnostic semantic channels (ARKit-52 or equivalent) + head pose.
- **Output**: values for target rig controls (shape keys, bones, or controller properties).
- **Rig profiles** (support order):
  1. ARKit-52 shape key rigs (commodity — name-based mapping).
  2. Rigify / FaceIt facial rigs (Blender standard).
  3. Generic bone-based autorigs via **assisted rig probing**: the user (or the addon) poses canonical expressions; the system learns control response and range, then solves live animation against the profile.
  4. Custom controller rigs.
- **Calibration**: neutral-pose subtraction + per-channel amplitude normalization per performer; per-rig range calibration from probing.
- **Correctives**: reactive to *combinations* of control values (pose-space), not per-channel thresholds.

## 8. Recording & Bake

- Live preview mode (properties only) vs capture mode (batched keyframe insertion at chosen FPS).
- Bake to F-curves on the target rig; export path validated with FBX (known pain point with autorig exports — see research).
- Reproducible sessions: capture runs are logged with backend, settings, and packet stream for replay.

## 9. Licensing & Attribution

| Component | License | Notes |
|---|---|---|
| MediaPipe Face Landmarker + models | Apache-2.0 | Redistribution permitted; keep notice |
| OpenSeeFace | BSD-2-Clause | Keep notice; external process |
| RealCapture open-side (Blender addon) | TBD (MIT vs GPL — decision before release) | Shapes which existing addon code may be referenced |
| RealCapture mapping layer | Private (IP) | Not distributed with open-side code |

Excluded due to non-commercial licenses: DECA/EMOCA/EmoTalk, InsightFace pretrained models (incl. LivePortrait's bundled models).

## 10. Demo Assets Policy

VALORANT assets (Riot Games) are used **only** for private educational/technical demonstration. They are **never** included in the open-source repository, documentation, or media accompanying the release. Open-source demo content will use original or permissively licensed rigs.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Blender timer jitter under heavy scenes | Epsilon gating, Simplify guidance, telemetry |
| OpenSeeFace/MediaPipe environment conflicts in Blender's Python | Backends run as separate processes with own venv; Blender side stays dependency-light |
| Rig probing UX too complex for generic autorigs | Start with presets for Rigify/FaceIt; probe only as advanced path |
| ARKit-52 semantic drift between backends | Channel normalization layer + per-backend unit tests |
| Scope creep before local-phase quality | Roadmap gate: no open-source work before M4 exit |

## 12. References

See `docs/research/facial-capture-landscape.md` for the full research pass with sources.

# Facial Capture Landscape — Research Findings (Pass 1)

RealCapture — real-time facial expression capture for Blender.
Scope: expression fidelity, latency/performance, rig compatibility, state of the art.
Date: 2026. All findings below are backed by the linked sources; private methodology is intentionally not documented here.

---

## 1. Expression fidelity

### Key findings
- **FACS / Action Units as the semantic vocabulary.** Production-quality facial capture ties rig deformation to observable muscle actions (AUs), not to emotion labels. FACS gives the fine-grained movement vocabulary; blendshapes/controls are the rig's deformation layer.
  - Sources: [ScienceDirect — AU detection/classification](https://www.sciencedirect.com/science/article/pii/S0921889099001037), [Bath — Reading Between The Dots (3D markers + FACS)](https://researchportal.bath.ac.uk/en/publications/reading-between-the-dots-combining-3d-markers-and-facs-classification/)
- **Calibrate a true neutral first.** Record a relaxed neutral pose and subtract its values from subsequent frames to remove person-specific resting-face bias.
  - Source: [Nature — blendshape analysis with calibration](https://www.nature.com/articles/s41531-026-01579-2)
- **Calibrate amplitude per person and per channel.** Ask for isolated low/medium/max poses (brows, lids, cheeks, lips, jaw, left/right). Never treat tracker value `1.0` as anatomically correct — normalize to the performer's achievable range.
- **Corrective / coupled shapes are a separate layer.** Independent linear blendshapes miss wrinkles, lip sealing/rolling, cheek–eye coupling, extreme mouth shapes. Disney's production pipeline combines deformers with pose-space deformation (PSD); correctives should be driven by the *combination* of primary controls, not independently from capture.
  - Sources: [Disney — Deformer-Based Facial Rigging](https://media.disneyanimation.com/uploads/production/publication_asset/97/asset/facial.pdf), [Disney Research — Local Anatomically-Constrained Retargeting](https://studios.disneyresearch.com/2022/07/24/local-anatomically-constrained-facial-performance-retargeting/)
- **Measure two separate outcomes:**
  1. Tracking fidelity: landmark/mesh error, temporal jitter, coefficient error.
  2. Expression accuracy: AU presence, intensity, onset/peak/offset timing, human perceptual ratings.
  Geometric fidelity correlates poorly with perceived expression quality — perceptual testing matters.
  - Source: [SIGGRAPH — FaceExpressions-70k perceived expression differences](https://camps.aptaracorp.com/ACM_PMS/PMS/ACM/SIGGRAPHCONFERENCEPAPERS25/64/1c2393e6-1a26-11f0-ada9-16bb50361d1f/OUT/siggraphconferencepapers25-64.html)
- **Signal cleaning is a research-grade problem.** Facial dynamics contain both low- and high-frequency motion; humans are expert at perceiving facial-motion inconsistency. Real-time cleaning/refinement of capture signals is an active area.
  - Sources: [arXiv — Real-Time Cleaning and Refinement of Facial Animation Signals](https://arxiv.org/pdf/2008.01332.pdf), [arXiv — FACEGOOD single-camera capture](https://arxiv.org/html/2111.07556v1)

### Implications for RealCapture
- A calibration pass (neutral + per-channel range) is table stakes for fidelity, not a nice-to-have.
- Adaptive smoothing (not fixed low-pass) is needed: fixed smoothing adds latency and kills micro-expressions; no smoothing produces jitter.
- Correctives should react to combined control values (pose space), not per-channel thresholds.

---

## 2. Latency and performance

### Key findings (Blender-specific)
- **Blender Python threads are NOT thread-safe.** Blender's docs explicitly warn against persistent Python threads touching `bpy` — crashes result. The safe architecture is: inference in a separate process, Blender consumes via main-thread mechanisms only.
  - Source: [Blender API — Python Threads are Not Supported](https://docs.blender.org/api/main/info_gotchas_threading.html)
- **Recommended pipeline (community-validated pattern):**
  ```
  capture/inference worker (separate process)
    → compact IPC packet (pose + 20–52 expression coefficients, not raw landmarks)
    → non-blocking socket
    → bpy.app.timers callback on main thread (30–60 Hz)
    → latest-frame-wins (drain queue, keep newest, drop stale)
    → write custom properties on one controller object
    → native Blender drivers → bones / shape keys
  ```
  - Sources: [Blender API — Application Timers](https://docs.blender.org/api/5.0/bpy.app.timers.html), [Blender dev docs — Dependency Graph](https://developer.blender.org/docs/features/core/depsgraph/), [Google AI — MediaPipe FaceLandmarker LIVE_STREAM](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarker)
- **Latency rules:**
  - Keep only the newest packet; older facial frames are worse than dropped frames.
  - Never block inside a driver expression; never `recvfrom` on a blocking socket in the UI thread.
  - Avoid Python driver expressions — native drivers evaluate with more parallelism.
  - Skip writes below an epsilon (change detection) to avoid pointless depsgraph evaluations.
- **Separate preview from record.** Preview: update controller properties only. Record: sample at fixed FPS and insert keyframes in batches or post-capture — never keyframe every incoming packet.
- **Viewport cost dominates perceived latency.** Blender's Simplify settings (subdivision, texture resolution, etc.) materially affect the feedback loop.
  - Source: [Blender Manual — Simplify](https://docs.blender.org/manual/en/5.2/render/cycles/render_settings/simplify.html)
- **Industry reference points:** NVIDIA Audio2Face-3D streams ARKit 52 blendshapes @ 60 FPS over gRPC; VTuber streaming research offloads inference to keep mobile power draw sane. Real-time face systems consistently converge on "compact coefficient stream + latest-wins consumption."
  - Sources: [NVIDIA forums — Audio2Face streaming](https://forums.developer.nvidia.com/t/audio2face-digital-human-sdk-v3-0-diffusion-model-frame-gap-during-streaming-inference-posting-here-as-digital-human-board-is-closed/361109), [ACM — Power Efficient Mobile VTuber Live Streaming](https://dl.acm.org/doi/fullHtml/10.1145/3595916.3626427)

### Implications for RealCapture
- Latency budget should be measured end-to-end (camera → inference → IPC → Blender apply → viewport) with per-stage telemetry.
- If the current implementation uses Python threads inside Blender or blocking sockets, those are the first stability suspects.
- The IPC boundary is also the natural IP boundary: the private inference engine can ship as a closed binary while the Blender side is open source.

---

## 3. Rig compatibility

### Key findings
- **Do NOT map capture channels directly to arbitrary rig controls.** The consensus architecture is a semantic intermediate representation (ARKit 52 / FACS AUs / landmarks), then per-rig calibration:
  1. Capture → canonical semantic channels (rig-independent).
  2. Per-character calibration: probe the rig with a small set of canonical expressions to learn the mapping and each control's usable range.
  3. Anatomically-constrained solve (pure least-squares produces implausible mouths/lids).
  4. Corrective layer driven by combined controls.
  5. Artist override for cleanup.
  - Sources: [PMC — Appearance Agnostic Facial Retargeting Pipeline](https://pmc.ncbi.nlm.nih.gov/articles/PMC11653099/), [ACM TOG — Facial retargeting with automatic range of motion alignment](https://doi.org/10.1145/3072959.3073674)
- **Levels of automation by rig type:**
  | Target rig | Feasible automation |
  |---|---|
  | Standardized blendshape rig (ARKit-52-like) | Largely automatic (semantic mapping + range scaling + filtering) |
  | Arbitrary control rig | Semi-automatic: one-time "rig probing"/calibration library |
  | Neutral mesh only | Auto-generate intermediate FACS/blendshape rig, then drive it |
  | Stylized creatures | Artist-defined semantic adapter (lip purse → snout compression, etc.) |
- **FaceIt (Blender) is the de facto standard**: it generates a Rigify-based face rig, an ARKit Control Rig with automatic drivers connecting bones to the 52 shape keys, and is the recommended companion for face capture in Blender. Its shape poses are Rigify-compatible.
  - Sources: [FaceIt docs — FAQ](https://faceit-doc.readthedocs.io/en/latest/FAQ/), [FaceIt docs — Control Rig](https://faceit-doc.readthedocs.io/en/latest/control_rig/), [Blender Studio — Facial Rigging with shape keys](https://studio.blender.org/blog/proposal-facial-rigging-with-shape-keys/)
- **AdvanceSkeleton (Maya) pattern** (user's reference point): facial rig = joints + blendshapes connected by the plugin; mocap is applied via constraint/HIK-style retargeting, not direct channel mapping. Same lesson: a bridge/calibration layer is required; there is no universal direct mapping.
  - Sources: [Autodesk forums — mocap with Advanced Skeleton](https://forums.autodesk.com/t5/maya-animation-and-rigging-forum/how-can-i-use-mocap-animation-with-advanced-skeleton/td-p/11109897), [Gnomon — FACS Rigging for Facial Motion Capture](https://thegnomonworkshop.com/tutorials/facs-rigging-for-facial-motion-capture)
- Baking pattern: mapping pose libraries/F-curves from a control layer to an arbitrary rig is scriptable (see community gists summing scaled partial poses) — confirms a profile-based mapping approach works.
  - Source: [Gist — Bake Faceit/Audio2Face animations directly to a rig](https://gist.github.com/gabrielmontagne/663b0dd10c6bd7fe3a2376b47f083819)

### Implications for RealCapture
- The rig-profile layer (calibration + mapping per autorig) is the strongest differentiator: every competitor assumes ARKit-52 shape keys; generic mapping to bone-based autorigs is the unsolved part.
- Support order: (1) ARKit-52 shape keys (commodity), (2) Rigify/FaceIt rigs (Blender standard), (3) generic bone autorigs via probing, (4) custom controllers.

---

## 4. State of the art / competition

### Commercial
| Tool | Model | Notes |
|---|---|---|
| **FaceIt** | ~$99 one-time (Blender addon) | Full pipeline: rigging → shapekeys → control rig → mocap apply. ARKit-52 optimized. The Blender benchmark to beat. |
| **Rokoko** | Hardware + subscription | Suite integration; recommends FaceIt for ARKit blendshape rigs. |
| **AccuFACE (Reallusion)** | Paid | Windows webcam-based ARKit-style capture. |
| **Live Link Face (Epic)** | Free (iOS) | iPhone TrueDepth ARKit-52 streaming; the interoperability reference format. |
| **Audio2Face (NVIDIA)** | Free/paid SDK | ARKit-52 @ 60 FPS streaming over gRPC; audio-driven, not video. |

Sources: [Rokoko — How to choose a face capture solution](https://www.rokoko.com/insights/how-to-choose-the-best-face-capture-solution-for-animation), [FaceIt on Superhive](https://superhivemarket.com/products/faceit/ratings), [Reddit — What rig to use for facecapture](https://www.reddit.com/r/Rokoko/comments/uz45nt/what_rig_to_use_for_facecapture/)

### Open source (Blender)
| Project | License | Notes |
|---|---|---|
| [Blender-Face-Animation](https://github.com/VKG5/Blender-Face-Animation) | MIT | MediaPipe Face Landmarker, webcam/video → shape keys and/or bones. Closest free match. |
| [MoCapkiteFA](https://github.com/BlenderDefender/MoCapkiteFA) | GPL-3.0 | CG Matter-style 3-step facial mocap workflow; Blender 4.2. |
| [DeadFace](https://github.com/Qaanaaq/DeadFace) | OSS | MediaPipe-based; designed to complement FaceIt. |
| [BlendCap](https://github.com/Arcomade/BlendCap) | GPL | Body/hands/face capture from single-camera video. |
| [facecap](https://github.com/effectustasi/facecap) | OSS | ARKit + MediaPipe for MetaHuman-in-Blender. |
| [FreeFaceMoCap](https://github.com/MohamedAliRashad/FreeFaceMoCap) | OSS | Older face tracking module. |

### Interoperability standards worth supporting
- **ARKit-52 blendshape set** — the de facto interchange format across Live Link Face, Rokoko, VSeeFace, AccuFACE, Audio2Face.
- **OSC / VMC protocol** — the VTuber ecosystem's transport (VSeeFace, Unity); an OSC input/output makes RealCapture composable with that ecosystem.
  - Sources: [VSeeFace manual — VMC protocol](https://github.com/emilianavt/VSeeFaceManual/blob/master/README.md), [VRM blendshape setup](https://vrm.dev/en/univrm/blendshape/blendshape_setup/), [OSC Controller for Blender](https://superhivemarket.com/products/osc-controller/docs)

### Gap analysis (where RealCapture can differentiate)
1. Generic mapping to **bone-based autorig rigs** (Rigify without FaceIt, custom autorigs) — everyone else assumes ARKit shape keys.
2. **Calibration per performer and per rig** in one open tool (commercial tools assume their own rig generation).
3. Open transport (OSC/UDP) so the private inference engine can be swapped — IP stays closed, ecosystem stays open.

---

## 5. Capture-engine shortlist (pass 2, licenses verified)

| Repo | License | Role in RealCapture |
|---|---|---|
| [google-ai-edge/mediapipe-samples](https://github.com/google-ai-edge/mediapipe-samples) / MediaPipe Face Landmarker | Apache-2.0 | Default backend: 478 landmarks + 52 ARKit blendshapes + head pose, webcam, real time. `.task` models redistributable. |
| [emilianavt/OpenSeeFace](https://github.com/emilianavt/OpenSeeFace) | BSD-2-Clause | Alternative backend: 30–60 fps CPU, more robust in low light/noise/wide head poses, UDP external-process design. |
| [yeemachine/kalidokit](https://github.com/yeemachine/kalidokit) | MIT | Solver logic reference: landmark → rig values (euler + blendshape weights). JS, portable to Python. |
| [Daniel-W-Blender-Python/VIPER-Blender-Facial-Motion-Capture](https://github.com/Daniel-W-Blender-Python/VIPER-Blender-Facial-Motion-Capture) | MIT | Minimal Blender integration reference (MediaPipe → Rigify bones). ~485 lines; hardcodes Rigify bone names ("cheek.B.R.001"), key_step keyframing, no timers/threads — confirms the arbitrary-rig mapping gap. |
| [philgatt/Blender-Face-Motion-Capture-AR-Kit](https://github.com/philgatt/Blender-Face-Motion-Capture-AR-Kit) | — | Secondary reference: MediaPipe → ARKit shape keys. |
| [Arcomade/BlendCap](https://github.com/Arcomade/BlendCap) | GPL | Secondary reference: body/hands/face from single video. |

**Do not use (non-commercial licenses):** DECA / EMOCA / EmoTalk (Max Planck "Other" licenses), InsightFace pretrained models, LivePortrait's bundled models.

---

## Open questions (user decisions, private)
1. Input contract of the private engine: what does it emit (ARKit-52? AUs? custom channels?) — needed to design the public mapping layer without exposing methodology.
2. Blender version floor (4.2 LTS is the community baseline).
3. OS targets for local phase (Windows first?).
4. Open-source license preference (GPL vs MIT shapes which addons' code can be referenced).

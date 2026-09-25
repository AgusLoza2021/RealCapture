# Feature: RealCapture Planning (research + work plan)

## Goal
Research the real-time facial capture landscape and produce the planning documents
(research findings, technical design doc, roadmap) for the RealCapture project.

## Tasks
- [x] Research: expression fidelity (FACS, calibration, smoothing, jitter) — 2026, sources in docs/research/
- [x] Research: latency and performance (Blender threading model, IPC, timers) — 2026, sources in docs/research/
- [x] Research: rig compatibility (intermediate representation, autorig mapping) — 2026, sources in docs/research/
- [x] Research: state of the art / competition (commercial + open source) — 2026, sources in docs/research/
- [x] Synthesize findings into docs/research/facial-capture-landscape.md- [x] Research pass 2: GitHub capture-engine repos evaluated (MediaPipe, OpenSeeFace, Kalidokit, VIPER) — licenses checked, findings in chat + landscape doc
- [ ] User defines private design decisions (input type, rig profiles, OS target) — blocked on user
- [x] Write docs/realcapture-tdd.md (public-facing technical design doc, private methodology redacted)
- [x] Write docs/roadmap.md (milestones M0–M5)
- [x] Locked decisions: both backends (MediaPipe default + OpenSeeFace alt), Blender 4.2 LTS, Windows-first
- [x] Git repository initialized, M0 committed — commit cefe2a0 (docs: add TDD v0.1, roadmap (M0-M5), and capture-landscape research)
- [ ] Review workload check: split docs into reviewable work-unit commits

## Constraints
- Underlying implementation/methodology stays private (IP). No implementation details in public docs.
- VALORANT assets: educational/demo reference only, no Riot affiliation.
- Path: local-first quality, then open-source release.

## Evidence
- (none yet — planning phase)

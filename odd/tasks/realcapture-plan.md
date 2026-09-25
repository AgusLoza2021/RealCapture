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
- [ ] Public README stub (positioning + IP note, no methodology) — the last open M0 item; no root `README.md` exists yet
- [ ] Review workload check: split docs into reviewable work-unit commits

## Constraints
- Underlying implementation/methodology stays private (IP). No implementation details in public docs.
- VALORANT assets: educational/demo reference only, no Riot affiliation.
- Path: local-first quality, then open-source release.

## Evidence
- Planning phase: `docs/research/`, `docs/realcapture-tdd.md`, `docs/roadmap.md`.
- 2026-09-25: `docs/roadmap.md` reconciled against verified evidence — the git/M0-commit item checked against `cefe2a0`, M1's six items checked with verified commit references (`eff08f4`, `0f9dd87`, `2cc9d57`, `f59567d`), and M1 set to `In progress` rather than `Done` because its latency exit criterion is not met. See `odd/tasks/milestone-closure-m0-m1.md`.

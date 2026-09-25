# Feature: Companion Dashboard (capture control + live telemetry UI)

Web dashboard served by the capture backend so a user can start/stop capture,
watch live telemetry (FPS, transport latency, active channels), and record
sessions from any browser on the LAN — including a phone, which makes it the
primary demo vehicle for showing the tool.

Design guidance: ~/.agents/skills/frontend-design/SKILL.md (Anthropic
frontend-design, installed 2026-09).

## Work units

- [ ] U1. Dashboard hub (pure logic): connection/session state machine,
      ring buffers for FPS + latency, channel activity aggregation, a
      broadcast hub (subscribe/publish) decoupled from any web framework.
      Unit tests without fastapi.
- [ ] U2. HTTP/WS server: FastAPI app serving the dashboard + WebSocket that
      streams state at ~10 Hz, REST endpoints (status, start/stop capture,
      record toggle), wired to run_capture (also usable standalone via
      `python -m backend.run_dashboard`). fastapi + uvicorn as optional
      extras in requirements; tests import-guarded (skip if not installed).
- [ ] U3. Frontend: single static page (vanilla HTML/JS, dark theme): status
      header, FPS/latency sparklines, top active channels bar list, engine
      selector, start/stop + record controls, session file indicator.
- [ ] U4. Docs: backend/README dashboard section + quickstart demo script
      (PC + phone on same Wi-Fi).

## Constraints

- Runs in the BACKEND process: threads are fine there; never touches bpy.
- Open-source layer (connection/UX), no solver logic.
- Windows-first: binding 0.0.0.0 must print LAN instructions for phone access.
- No heavy frontend build tooling: static assets only (aligns with local-first
  and keeps the diff reviewable).

## Evidence

- (append per work unit)

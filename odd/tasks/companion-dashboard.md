# Feature: Companion Dashboard (capture control + live telemetry UI)

Web dashboard served by the capture backend so a user can start/stop capture,
watch live telemetry (FPS, transport latency, active channels), and record
sessions from any browser on the LAN — including a phone, which makes it the
primary demo vehicle for showing the tool.

Design guidance: ~/.agents/skills/frontend-design/SKILL.md (Anthropic
frontend-design, installed 2026-09).

## Work units

- [x] U1. Dashboard hub (pure logic): connection/session state machine,
      ring buffers for FPS + latency, channel activity aggregation, a
      broadcast hub (subscribe/publish) decoupled from any web framework.
      Unit tests without fastapi.
- [x] U2. HTTP/WS server: FastAPI app serving the dashboard + WebSocket that
      streams state at ~10 Hz, REST endpoints (status, start/stop capture,
      record toggle), wired to run_capture (also usable standalone via
      `python -m backend.run_dashboard`). fastapi + uvicorn as optional
      extras in requirements; tests import-guarded (skip if not installed).
      (Deviations: standalone entry is `python -m backend.dashboard.server`;
      engine selection lives in run_capture CLI, not the dashboard.)
- [x] U3. Frontend: single static page (vanilla HTML/JS, dark theme): status
      header, FPS sparkline, top active channels meter console, stop capture
      control, recording path indicator. (Deviations: no engine selector —
      engine is chosen when starting the backend.)
- [x] U4. Docs: backend/README dashboard section (PC + phone LAN usage).

## Constraints

- Runs in the BACKEND process: threads are fine there; never touches bpy.
- Open-source layer (connection/UX), no solver logic.
- Windows-first: binding 0.0.0.0 must print LAN instructions for phone access.
- No heavy frontend build tooling: static assets only (aligns with local-first
  and keeps the diff reviewable).

## Evidence

- U1 `9653c4e`: backend/dashboard/hub.py (DashboardHub + BroadcastHub),
  17 tests with FakeClock, no sleeps.
- U2 `13e7307`: backend/dashboard/server.py, run_capture `--dashboard PORT`,
  base.py on_packet/on_send_error hooks with proc_ms timing, 8 server tests.
  Gotcha (documented by test): FastAPI resolves endpoint annotations against
  module globals — fastapi imports must stay at module level in server.py,
  a function-local import turns `websocket: WebSocket` into a missing query
  param and the route closes with 1008/403 before accept().
- U3 `8023928`: backend/dashboard/static/index.html — graphite studio
  console theme, VU-style channel meters, canvas FPS sparkline, two-click
  stop confirm, WS auto-reconnect, system fonts only (offline/local-first).
- U4: backend/README.md — dashboard section + LAN/phone quickstart.
  Full suite: 136 passed.

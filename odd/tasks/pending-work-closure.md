# Pending work closure

## Objective

Close the remaining owner-approved work across RealCapture and the Telegram bridge: publish completed branches, reconcile the competing broker fixes, exercise the real launch paths, make the remaining technical decisions explicit, and update the local memory package only after runtime work is quiet.

## Why

The implementation is substantially complete but is split across local-only branches and two repositories. The owner explicitly authorized completing all remaining work, including Git publication and integration.

## Scope

- Publish and integrate `blender-native-plugin` (10 existing work-unit commits).
- Publish and integrate `phase2/weight-zones` (5 existing work-unit commits).
- Reconcile pi-telegram-bridge PR #4 with local `feat/voice-transcription`.
- Verify the double-click launchers and the Blender panel with the available real camera/MPFB2 rig.
- Close decisions that can be resolved from evidence; preserve unresolved empirical claims honestly.
- Update `gentle-engram` from 0.1.12 to 0.1.16 last.

## Constraints

- Technical artifacts stay in English.
- Existing branch commits are work units; do not squash behavior and tests apart.
- RealCapture has no repository Issue Forms or PR templates. The issue-first PR skill cannot be satisfied without inventing policy, so publication uses verified direct integration rather than a nonconforming PR.
- The Telegram bridge has competing fixes: PR #4 removes PT5M repetition; local `feat/voice-transcription` keeps PT5M and makes the hidden launcher wait so `IgnoreNew` absorbs retries. One semantic model must win.
- No false green: every live check must distinguish absence, reuse, stale data, and actual success.
- The existing MPFB2 asset under `%LOCALAPPDATA%/Temp/rc_mpfb` is the first real rig because it is already installed and previously proved 52/52 shape-key movement.
- `gentle-engram` updates only after Blender, backend, broker, and verification work are quiet.

## Verification mode

- ODD TDD mode: not configured; use ordinary focused and full verification.
- Canonical RealCapture suite: `python -m pytest tests -q`.
- Canonical bridge suite: `npm test` and `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test.ps1`.
- RDD is enabled; each new work-unit commit is assessed at its committed boundary.

## Delivery strategy

- Strategy: existing work-unit commits plus direct verified integration.
- Reason: the completed branches exceed the review budget, but RealCapture cannot open a conforming issue-linked PR because the repository has no YAML Issue Forms. No issue or approval will be fabricated.
- Publish feature refs before updating `main`, so every original boundary remains recoverable.

## Tasks

- [ ] C1 — Verify, publish, and integrate `blender-native-plugin`.
  - Route: delegated verification (`gentle-ai-verify`); publication/integration inline Git operations.
  - Acceptance: canonical suite passes; Blender extension builds and validates; feature branch is pushed; `main` contains `7a55a05` plus this closure record; origin readback matches.
- [ ] C2 — Rebase, verify, publish, and integrate `phase2/weight-zones`.
  - Route: delegated verification; rebase/integration inline Git operations.
  - Acceptance: five work units remain intact, conflicts are resolved without dropping the dashboard refusal fix, canonical suite passes, branch and `main` are pushed.
- [ ] C3 — Reconcile the Telegram broker semantics.
  - Route: delegated mapper/writer because the decision spans service scripts, launcher, docs, and tests.
  - Acceptance: one coherent on-demand model, no console flash, no duplicate broker, tests mutation-capable, PR #4 closed or superseded with an explicit reason.
- [ ] C4 — Publish and verify the final Telegram branch.
  - Route: delegated verification; GitHub operations inline.
  - Acceptance: `npm test` and Windows PowerShell suite pass; branch is pushed; publication state is read back from GitHub.
- [ ] C5 — Live-test `control-room.cmd` and `camera-to-rig.cmd`.
  - Route: delegated external/runtime verification.
  - Acceptance: process, ports, dashboard, camera, packet flow, and cleanup are observed; failures are reported, not inferred away.
- [ ] C6 — Live-test Blender Start with the existing MPFB2 rig.
  - Route: delegated external/runtime verification.
  - Acceptance: the installed extension starts its own child, MPFB2 loads, 52/52 sweep remains live, dashboard lights are truthful, and all children are cleaned up.
- [ ] C7 — Close the remaining technical decisions.
  - Route: inline synthesis from verified evidence.
  - Acceptance: MPFB2/shape-key-first rig path and reversible weight-zone policy are recorded; M1's 30-minute stall and post-inference latency blind spot remain explicitly open unless newly measured.
- [ ] C8 — Update `gentle-engram` 0.1.12 to 0.1.16.
  - Route: delegated install verification.
  - Acceptance: runtime processes are quiet, installed version reads 0.1.16, Pi memory health check succeeds or the restart requirement is reported.

## Progress

- Mapping completed: `blender-native-plugin` is 10 commits ahead of `origin/main`; `phase2/weight-zones` is 5 independent commits ahead; bridge PR #4 is open while local `feat/voice-transcription` implements a competing PT5M/IgnoreNew strategy.
- Owner authorization received: "Dale, encargate de resolver todo eso."

## Next step

Run C1 verification, then publish and integrate the Blender plugin branch.

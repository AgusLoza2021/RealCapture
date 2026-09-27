# Pending work closure

## Objective

Close the remaining owner-approved RealCapture / Blender-Camera work: exercise the real launch paths, prove the Blender panel against the available MPFB2 rig, and record the remaining technical decisions without overstating empirical evidence.

## Why

The RealCapture implementation and its two completed feature branches are published, but the owner-facing launch paths and final MPFB2 integration still need fresh live evidence.

## Scope

- Preserve the completed publication and integration evidence for `blender-native-plugin` and `phase2/weight-zones`.
- Verify the double-click launchers and the Blender panel with the available real camera/MPFB2 rig.
- Close decisions that can be resolved from evidence; preserve unresolved empirical claims honestly.
- Work only in RealCapture / Blender-Camera. `pi-telegram-bridge` and package maintenance belong to other sessions and are out of scope here.

## Constraints

- Technical artifacts stay in English.
- Existing branch commits are work units; do not squash behavior and tests apart.
- RealCapture has no repository Issue Forms or PR templates. The issue-first PR skill cannot be satisfied without inventing policy, so publication uses verified direct integration rather than a nonconforming PR.
- No false green: every live check must distinguish absence, reuse, stale data, and actual success.
- The existing local MPFB2 environment is the first real rig because it is already installed and previously proved 52/52 shape-key movement; its machine-specific path remains outside tracked files.
- Avoid OS focus/click automation while the owner uses the machine; prefer Blender-internal redraw and screenshot operators.

## Verification mode

- ODD TDD mode: not configured; use ordinary focused and full verification.
- Canonical RealCapture suite: `python -m pytest tests -q`.
- RDD is enabled; each new work-unit commit is assessed at its committed boundary.

## Delivery strategy

- Strategy: existing work-unit commits plus direct verified integration.
- Reason: the completed branches exceed the review budget, but RealCapture cannot open a conforming issue-linked PR because the repository has no YAML Issue Forms. No issue or approval will be fabricated.
- Publish feature refs before updating `main`, so every original boundary remains recoverable.

## Tasks

- [x] C1 — Verify, publish, and integrate `blender-native-plugin`.
  - Route: delegated verification (`gentle-ai-verify`); publication/integration inline Git operations.
  - Evidence: `524 passed, 1 warning`; extension build exit 0 (`realcapture-0.1.0.zip`, 61151 bytes); Blender validator exit 0; `blender-native-plugin` and `main` both published at `6b470e5417f60a4cf0ffde3f9ab85e12da534468` with matching remote readback. Native committed-range review was unavailable (`schema-incompatible`, `lineage_created: false`), so the high-risk fallback used the independent verifier.
- [x] C2 — Rebase, verify, publish, and integrate `phase2/weight-zones`.
  - Route: delegated verification; rebase/integration inline Git operations.
  - Evidence: five original work units remained distinct after rebase; two README count conflicts were reconciled to the integrated total; focused tests reported 65 passed and the canonical suite reported 582 passed; stale pre-rebase evidence hashes were refreshed in `2a5e5f2`; feature and `main` remote refs both read back as `2a5e5f26756f2b26ad68d87fc49e093e14971059`. Backup `backup/phase2-weight-zones-pre-integration` retains original `7ca94c5`.
- [x] C3 — Live-test and harden `control-room.cmd` and `camera-to-rig.cmd`.
  - Route: delegated writer plus independent external/runtime verification.
  - Evidence: 591 tests pass; both launchers capture and validate an owned wrapper PID plus immutable start time before child-first cleanup. `control-room.cmd` proved API status, complete JPEG/MJPEG frames, advancing packets, truthful lights, exit 0, and cleanup without killing the co-hosted Windows Terminal. `camera-to-rig.cmd` proved the real MPFB2 character, a 52/52 target sweep, live packets 18→1044, honest shape-key-only rest-gate fallback, exact-PID Blender fallback close, and owned-tree cleanup. Deterministic drills proved malformed ownership exits 6 before Blender/backend and a refused stop exits 7 without printing false success; the remaining tree was then cleaned only by validated PID identity.
- [ ] C4 — Live-test Blender Start with the existing MPFB2 rig.
  - Route: delegated external/runtime verification.
  - Acceptance: the installed extension starts its own child, MPFB2 loads, 52/52 sweep remains live, dashboard lights are truthful, and all children are cleaned up.
- [ ] C5 — Close the remaining technical decisions.
  - Route: inline synthesis from verified evidence.
  - Acceptance: MPFB2/shape-key-first rig path and reversible weight-zone policy are recorded; M1's 30-minute stall and post-inference latency blind spot remain explicitly open unless newly measured.

## Progress

- C1 closed: the plugin branch and `main` are published at `6b470e5417f60a4cf0ffde3f9ab85e12da534468`; independent verification observed 524 tests, a successful extension build, and a successful Blender validator run.
- C2 closed: `phase2/weight-zones` was rebased, verified at 582 tests, published, and fast-forwarded into `main` at `2a5e5f26756f2b26ad68d87fc49e093e14971059`.
- The owner explicitly restricted this session to RealCapture / Blender-Camera; all Telegram bridge work is handed off to another session and must not be touched here.
- Live `control-room.cmd --no-browser --port 8799` evidence proved MediaPipe startup, advancing packets, complete JPEG/MJPEG frames, truthful camera/packet green and Blender red states, and port cleanup.
- The same live run exposed a candidate-caused safety defect: Windows Terminal co-hosted the named capture console, so `taskkill /FI "WINDOWTITLE eq ..." /T /F` terminated the shared `WindowsTerminal.exe` process and collateral terminal tabs.
- PID-ownership fix closed: normal exit 0 paths and deterministic exits 6/7 were observed live; the original Windows Terminal PID and start time survived every run, and no cleanup uses window titles or broad image matching.
- Five parallel subagents mapped the next work: installed-extension Start proof, camera-to-rig harness, M1 evidence gaps, rig/weight policy, and repo/ZIP/install synchronization. The installed extension is byte-identical to the current packaged add-on except that the post-package pure `rigprofile/weights.py` groundwork is absent; it has no production caller and does not block the Start proof.
- Owner authorization received: "Dale, encargate de resolver todo eso."

## Next step

Run C4 against the installed `bl_ext.user_default.realcapture` extension with the existing MPFB2 rig, proving backend Start/Stop ownership, dashboard truth, Blender heartbeat, live rig movement, and complete child cleanup.

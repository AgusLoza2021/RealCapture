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
- [x] C4 — Live-test Blender Start with the existing MPFB2 rig.
  - Route: delegated harness implementation, independent semantic verification, and one exclusive live camera/Blender run; coverage claim corrected 2026-09-27 after re-reading the immutable `proof.json` evidence.
  - Evidence: the installed `bl_ext.user_default.realcapture` extension started backend PID 18672 against a disposable copy of the MPFB2 character. It bound 52 shape channels (52 rig targets/bindings, matching C3's synthetic 52/52 target sweep and the dashboard heartbeat's 52 bound channels), applied 332 real MediaPipe packets, and moved actual driven shape keys (peak `mouthPucker=0.9322`), with all three dashboard lights changing from truthful initial red to final green. Stop Capture and Stop Backend both finished; extension state cleared, the child PID disappeared, UDP 11111 and TCP 8765 were independently rebound, and the baseline Windows Terminal PID survived.
  - Coverage correction: the report's raw producer evidence is 52 raw produced shape-key names = 51 of the 52 ARKit catalog names plus MediaPipe's extra `_neutral`; `tongueOut` is absent from the producer vocabulary. The earlier "52/52 live producer channels" wording compared raw count with catalog size and was false; honest producer coverage is `live 51/52` with `unexpected=['_neutral']`, `missing=['tongueOut']`. Rig bindings/targets (52), the C3 synthetic sweep (52/52), and the dashboard's 52 bound channels are separate facts and are not producer-vocabulary evidence. The harness now computes coverage from channel NAMES (`coverage_truth`, report schema `/2`) and enforces, with named constants and precise messages: exact catalog identity by SHA-256 digest over the sorted configured names (`EXPECTED_ARKIT_CATALOG_SHA256`, so a same-size catalog with a swapped name fails), a configured count of exactly 52, sentinel membership (`tongueOut` required, producer-only `_neutral` forbidden), a minimum of 51 live catalog matches, and zero-match fail-closed behavior.
  - Work-unit commit: `d813c51956d90a6637205b5b00115b4b71be61f1` (test(blender): prove installed Start lifecycle).
  - Native review transaction `review-e1b2163ded9e4352`: INCOMPLETE — review-risk was admitted, but review-resilience was repeatedly unavailable with `stopReason: length`; the independent verifier and the 638-test baseline passed. The coverage correction above supersedes the review-era wording.
  - Evidence artifact: `%TEMP%/rc-start-proof-20260927-154632/` (raw `observed_live_channel_names` in `proof.json`); focused harness tests: 73 passed; canonical suite: 664 passed, 1 third-party warning.
- [x] C5 — Close the remaining technical decisions.
  - Route: inline synthesis from verified evidence.
  - Recorded decisions: the MPFB2/ARKit shape-key-first path is the proven default (live C4 run moved real driven shape keys through the installed consumer); the bone path is gated and inactive (`no_head_bone` skip reason on this MPFB2 rig) and stays off until a rig with a usable head bone exists; `rigprofile/weights.py` is reversible R5a groundwork with no production caller — no destructive automatic weighting runs; R5b/R8/R9 remain open; the 30-minute M1 stall remains open; the post-inference latency blind spot remains open; short C3/C4 runs do not clear M1.
  - Work-unit commit: `a2bd1658407ddef279ed1d6578ac95ea464d489f` (`fix(blender): report ARKit coverage by channel identity`).

## Progress

- C1 closed: the plugin branch and `main` are published at `6b470e5417f60a4cf0ffde3f9ab85e12da534468`; independent verification observed 524 tests, a successful extension build, and a successful Blender validator run.
- C2 closed: `phase2/weight-zones` was rebased, verified at 582 tests, published, and fast-forwarded into `main` at `2a5e5f26756f2b26ad68d87fc49e093e14971059`.
- The owner explicitly restricted this session to RealCapture / Blender-Camera; all Telegram bridge work is handed off to another session and must not be touched here.
- Live `control-room.cmd --no-browser --port 8799` evidence proved MediaPipe startup, advancing packets, complete JPEG/MJPEG frames, truthful camera/packet green and Blender red states, and port cleanup.
- The same live run exposed a candidate-caused safety defect: Windows Terminal co-hosted the named capture console, so `taskkill /FI "WINDOWTITLE eq ..." /T /F` terminated the shared `WindowsTerminal.exe` process and collateral terminal tabs.
- PID-ownership fix closed: normal exit 0 paths and deterministic exits 6/7 were observed live; the original Windows Terminal PID and start time survived every run, and no cleanup uses window titles or broad image matching.
- Five parallel subagents mapped the next work: installed-extension Start proof, camera-to-rig harness, M1 evidence gaps, rig/weight policy, and repo/ZIP/install synchronization. The installed extension is byte-identical to the current packaged add-on except that the post-package pure `rigprofile/weights.py` groundwork is absent; it has no production caller and does not block the Start proof.
- C4 closed: the installed extension proved its own backend child, 52 bound MPFB2 channels, 332 applied packets, actual shape-key movement, final green camera/packet/Blender lights, and complete PID/port cleanup. The run used a disposable blend copy and did not persist machine-specific paths or preferences.
- C4 coverage corrected: raw produced names are 52 (51 ARKit + `_neutral`, `tongueOut` absent), so the honest producer claim is `live 51/52`; the original "52/52 live producer channels" was a raw-vs-catalog count conflation and is retracted. The harness now derives coverage from channel names (schema `/2`) and additionally enforces exact catalog identity by SHA-256 digest (`EXPECTED_ARKIT_CATALOG_SHA256`), a configured count of exactly 52, sentinels (`tongueOut` present, `_neutral` forbidden in configuration), and a minimum of 51 live catalog matches; zero matches remain fail-closed. The C3 synthetic 52/52 sweep stays separate evidence.
- The live backend was intentionally tree-terminated by the extension and reported process exit code 1 while still returning a successful stop result; independent PID and port probes proved cleanup. The C4 report therefore gates cleanup on observable ownership/state/PID/port truth rather than interpreting a forced Windows process exit code as graceful shutdown.
- Owner authorization received: "Dale, encargate de resolver todo eso."

## Next step

Publish `feat/installed-start-proof`, verify the remote feature SHA, then fast-forward `main` only after the committed C5 boundary passes its final independent verification. The failed 30-minute M1 soak, the post-inference latency blind spot, unwired weight application, and R5b/R8/R9 remain explicit open limits after publication.

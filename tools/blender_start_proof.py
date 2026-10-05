"""Bounded proof harness for the INSTALLED RealCapture extension (task C4).

Run inside Blender 4.5 (no ``--factory-startup``: the extension must already be
installed in ``user_default``), opening an existing character blend:

    blender --python tools/blender_start_proof.py -- --blend <character.blend> ^
        [--report proof.json] [--udp-port 11111] [--dashboard-port 8765] ^
        [--duration 12]

Or, without Blender, the pure self-test of the verdict layer:

    python tools/blender_start_proof.py --self-test

What the runtime layer proves, and how (every wait is bounded; every required
proof records observed evidence, never an assumption):

1.  The INSTALLED extension module is exactly ``bl_ext.user_default.realcapture``.
    The dev package ``addon`` is refused as a substitute: if it is enabled in
    the session, the harness stops instead of proving the wrong module.
2.  The extension is enabled only in-session if it was not already enabled.
    Preferences are never saved: ``wm.save_userpref`` is never called.
3.  Temporary preferences are set for this session: repository root (from
    ``RC_REPO_ROOT`` or ``--repo-root``), the derived venv interpreter, the
    UDP and dashboard ports, camera index 0, and no browser on start. The
    scene's UDP port is synced to the same value.
4.  The face mesh and armature are found, the controller empty is created or
    selected, and the INSTALLED scan/bind operators run. The report records
    shape/bone counts, whether the bone path is active, and the rest-gate
    skip reason verbatim.
5.  The installed ``realcapture.start_backend`` operator starts the child.
    The harness records the child PID, the exact reason, and the log path,
    then polls ``GET /api/status`` until it answers (bounded). The installed
    ``realcapture.start_capture`` operator then opens the consumer.
6.  In background mode the harness manually pumps the installed consumer's
    ``_tick()`` for a bounded duration while the REAL backend owns camera 0.
    No synthetic sender exists in real mode. It records applied packet
    samples, fps, transport latency, the dedicated fail-closed
    camera-to-rig acquisition latency block (valid samples, missing/invalid
    acquisition stamps, rolling avg/max and session max ms — availability
    and consistency only, no roadmap threshold), the dashboard's
    camera/packets/Blender lights verbatim, controller properties as
    diagnostics, and the ACTUAL rig target movement: accumulated non-Basis
    shape-key deviations over the whole window. Controller or metadata jitter alone can never green the
    movement gate. Raw observed producer channel names are the exact
    ``rc_shape_`` keys in the consumer's ``_last_values`` after the pump —
    data THIS run wrote, never pre-existing properties, pose keys, or
    metadata. Coverage is the NAME intersection against the installed
    catalog, never a count comparison.
7.  In ``finally``, capture and backend are always stopped through the
    installed operators, each exactly once; the harness never stops the
    ``BackendProcess`` object directly. Stop truth comes from the exact
    operator result objects (never a ``str(set)`` comparison), the cleared
    extension state, and the child PID being dead through an independent
    Windows query (``tasklist``, never the child's own handle). Port release
    is proven by binding: a UDP bind, and a fresh TCP bind+listen on the
    dashboard port (with ``SO_EXCLUSIVEADDRUSE`` on Windows, never
    ``SO_REUSEADDR``). No ``connect()`` is used: this host's firewall drops
    loopback SYNs to closed ports, so a connect to a RELEASED port can time
    out, and a timeout is never release evidence.
8.  The JSON report is written to the caller's path or the OS temp folder,
    and the process exits non-zero if any required proof failed. Absence,
    staleness, and unknown states are never green: the verdict layer
    (importable here without bpy) re-decides everything from the report.

Coverage honesty: no synthetic target sweep is executed or claimed by this
run; the historical 52/52 sweep (a per-channel drive of the rig targets) is
separate task evidence outside this report. Real producer coverage is only
ever claimed from the raw channel NAMES actually observed live in this run,
intersected with the configured catalog by ``coverage_truth`` — never from a
count comparison (52 raw names = 51 ARKit matches + ``_neutral`` is honest
51/52, not 52/52), and a run that observed zero catalog matches is never
green.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time

# -- pure constants (no bpy anywhere at module import) ------------------------------

#: The exact installed extension module this harness is allowed to prove.
RC_EXTENSION_MODULE = "bl_ext.user_default.realcapture"

#: The dev-package module that must never be substituted for the installed one.
DEV_PACKAGE_MODULE = "addon"

#: /3: the live evidence contract gains the fail-closed camera-to-rig
#: acquisition latency block, so a /2 report can never be mistaken for a
#: measured /3 run.
REPORT_SCHEMA = "realcapture-blender-start-proof/3"

#: The exact configured catalog size the C4 proof is defined against: the
#: full ARKit-52 vocabulary. C4 is specifically the installed default
#: MediaPipe + ARKit-52 proof, so a truncated (or grown) installed catalog is
#: a broken installation and can never ground a producer claim — not even an
#: internally consistent ``live 1/1`` with every name observed.
EXPECTED_CONFIGURED_CHANNELS = 52

#: The minimum observed catalog matches for an honest C4 pass: the known
#: MediaPipe contract is 51 of 52 (``tongueOut`` is never emitted, and
#: ``_neutral`` is producer-only). A producer that degraded below this
#: minimum is never green merely by being nonzero.
MINIMUM_LIVE_CATALOG_MATCHES = 51

#: Sentinel membership of the configured catalog: it must contain the ARKit
#: ``tongueOut`` channel and must NOT contain MediaPipe's producer-only
#: ``_neutral``. A 52-name count alone could pass a catalog patched to match
#: a degraded producer, or one that absorbed a producer artifact into
#: configuration; the sentinels pin the catalog to the actual ARKit-52
#: vocabulary, not just its size.
REQUIRED_CATALOG_SENTINEL = "tongueOut"
FORBIDDEN_CATALOG_SENTINEL = "_neutral"

#: Exact catalog identity: SHA-256 over the newline-joined, sorted, unique
#: configured channel names (UTF-8), computed from the shipped
#: ``addon/rigprofile/channels.py`` ARKIT_CHANNELS vocabulary. Count and
#: sentinels alone still accept a same-size catalog that swaps a non-sentinel
#: ARKit name for a fake one; the digest closes F1-F3 by pinning the exact
#: installed configuration the C4 proof is defined against.
EXPECTED_ARKIT_CATALOG_SHA256 = (
    "9585d1b9cf3548ca579910ced33615ba60bbc60c592fd7136bafa87e7db725c7"
)

#: The dashboard's own light ids (backend/dashboard/status_model.py), in order.
LIGHT_IDS = ("camera", "packets", "blender")

#: How old a dashboard snapshot may be and still count as live evidence.
MAX_SNAPSHOT_AGE_S = 5.0

DEFAULT_UDP_PORT = 11111
DEFAULT_DASHBOARD_PORT = 8765
DEFAULT_CAMERA_INDEX = 0
DEFAULT_PUMP_SECONDS = 12.0

#: Controller property prefixes written by the installed consumer.
SHAPE_PREFIX = "rc_shape_"

#: Report key prefix holding rig TARGET values (non-Basis shape keys). Only
#: these can prove actual rig movement; controller/pose/meta values are
#: diagnostics and can never green the movement gate by themselves.
RIG_TARGET_PREFIX = "shapekey::"

#: The exact real ARKit-52 vocabulary for the pure self-test, in canonical
#: order (mirrors ``addon/rigprofile/channels.py``; the pytest suite pins the
#: digest against the shipped module). Using the real names lets the healthy
#: self-test report pass the exact-catalog digest guard, and the raw set has
#: the exact shape of the live evidence: 51 observed names plus MediaPipe's
#: extra ``_neutral`` (the honest 51/52 producer claim the verdict accepts).
_SELF_TEST_CATALOG = (
    # Eyes
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft",
    "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft",
    "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight",
    "eyeLookUpRight", "eyeSquintRight", "eyeWideRight",
    # Jaw
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    # Mouth
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft",
    "mouthFrownRight", "mouthFunnel", "mouthLeft", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight", "mouthPucker",
    "mouthRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower",
    "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft",
    "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight",
    # Nose
    "noseSneerLeft", "noseSneerRight",
    # Cheeks
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    # Brows
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft",
    "browOuterUpRight",
    # Tongue
    "tongueOut",
)
_SELF_TEST_RAW = tuple(
    name for name in _SELF_TEST_CATALOG if name != "tongueOut"
) + ("_neutral",)


class ProofError(RuntimeError):
    """A required proof could not even be attempted; the message names why."""


# -- pure verdict layer (importable without bpy; unit-tested under pytest) ----------


def light_by_id(connections: object, light_id: str) -> dict | None:
    """The dashboard light with this id, or None. Absence is never green."""
    if not isinstance(connections, list):
        return None
    for light in connections:
        if isinstance(light, dict) and light.get("id") == light_id:
            return light
    return None


def light_is_green(light: object) -> bool:
    """Exact-identity green: ``"GREEN"`` or any other value is not green."""
    return isinstance(light, dict) and light.get("state") == "green"


def snapshot_is_fresh(
    fetched_at: object, now_s: object, max_age_s: float = MAX_SNAPSHOT_AGE_S
) -> bool:
    """True only for a real, non-stale snapshot. Never-fetched is never fresh."""
    if (
        not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool)
        or not isinstance(now_s, (int, float)) or isinstance(now_s, bool)
    ):
        return False
    return 0.0 < float(fetched_at) <= float(now_s) and (
        float(now_s) - float(fetched_at)
    ) <= max_age_s


def packets_progressing(samples: object, min_increase: float = 1.0) -> bool:
    """Whether a cumulative applied-packet series actually increased.

    Fewer than two clean numeric samples, a non-increasing series, or any
    non-numeric entry is not progress: absence is never green.
    """
    if not isinstance(samples, list) or len(samples) < 2:
        return False
    numbers: list[float] = []
    for sample in samples:
        if isinstance(sample, bool) or not isinstance(sample, (int, float)):
            return False
        value = float(sample)
        if not math.isfinite(value):
            return False
        numbers.append(value)
    return numbers[-1] - numbers[0] >= min_increase


def target_moved(peak_deviations: object, threshold: float = 1e-4) -> bool:
    """Whether the rig's TARGETS actually moved: non-Basis shape keys only.

    ``rc_meta_*``, ``rc_pose_*`` and ``rc_shape_*`` controller properties are
    diagnostics; only accumulated ``shapekey::<name>`` deviations (Basis
    excluded, both by construction at the source and again here by name) can
    satisfy the actual-rig movement gate.
    """
    if not isinstance(peak_deviations, dict):
        return False
    for key, value in peak_deviations.items():
        if not isinstance(key, str) or not key.startswith(RIG_TARGET_PREFIX):
            continue
        if key == f"{RIG_TARGET_PREFIX}Basis":
            continue
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= threshold
        ):
            return True
    return False


def live_shape_channel_names(last_value_keys: object) -> list[str]:
    """ARKit channel names written by THIS consumer run.

    The input is the key set of the consumer's ``_last_values`` (cleared at
    ``_begin``, filled only by packets this run applied). Only exact
    ``rc_shape_`` keys count: pre-existing controller properties, pose keys,
    and metadata never inflate live producer coverage.
    """
    if not isinstance(last_value_keys, (set, frozenset, list, tuple)):
        return []
    names: set[str] = set()
    for key in last_value_keys:
        if isinstance(key, str) and key.startswith(SHAPE_PREFIX):
            name = key[len(SHAPE_PREFIX):]
            if name:
                names.add(name)
    return sorted(names)


FINISHED_OPERATOR_RESULT = frozenset({"FINISHED"})


def operator_finished(result: object) -> bool:
    """Exact operator-result identity: only ``{'FINISHED'}`` counts.

    Comparing ``str(result)`` is forbidden: it would accept any object whose
    repr looks finished. Blender operator results are sets, so the exact set
    identity is the only honest truth here.
    """
    return isinstance(result, (set, frozenset)) and set(result) == {"FINISHED"}


def operator_repr(result: object) -> str:
    """A JSON-safe record of an operator result; it never decides truth."""
    if isinstance(result, (set, frozenset)):
        return ", ".join(sorted(str(item) for item in result)) or "(empty)"
    if result is None:
        return "none"
    return str(result)


def movement_from_samples(
    baseline: object, samples: object, threshold: float = 1e-4
) -> dict[str, float]:
    """Peak deviation from ``baseline`` per numeric key over the WHOLE window.

    The runtime pump samples properties periodically, so a value that spiked
    mid-window and returned to baseline by the final sample is still seen:
    final-only comparison would hide exactly the movement the proof needs.
    A key absent from the baseline (a newly written property) measures its
    absolute value, so a zero value is honestly not movement.
    """
    deviations: dict[str, float] = {}
    if not isinstance(samples, list):
        return deviations
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        for key, value in sample.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                continue
            base = baseline.get(key) if isinstance(baseline, dict) else None
            if (
                isinstance(base, bool)
                or not isinstance(base, (int, float))
                or not math.isfinite(float(base))
            ):
                deviation = abs(float(value))
            else:
                deviation = abs(float(value) - float(base))
            if deviation > deviations.get(key, 0.0):
                deviations[key] = deviation
    return deviations


def window_moved(deviations: object, threshold: float = 1e-4) -> bool:
    """Whether any accumulated peak deviation crossed ``threshold``."""
    if not isinstance(deviations, dict):
        return False
    return any(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and float(value) >= threshold
        for value in deviations.values()
    )


def wait_until(
    predicate,  # noqa: ANN001 - callable, typed loosely for pure injection
    timeout_s: float,
    interval_s: float = 0.05,
    clock=time.monotonic,
    sleep=time.sleep,
) -> tuple[bool, float]:
    """Bounded wait: poll ``predicate`` until it is true or the deadline hits.

    Returns ``(ok, elapsed_s)``. The predicate is checked at the deadline
    itself (inclusive boundary) and the total wait never exceeds the timeout:
    a harness must never hang waiting for something that will not come. A
    hard iteration cap additionally guarantees termination even when an
    injected clock never advances (the defect class of the original fake-clock
    tests, where a no-op ``sleep`` left the clock frozen forever).
    """
    start = clock()
    deadline = start + timeout_s
    max_iterations = max(2, math.ceil(timeout_s / max(interval_s, 1e-9)) + 10)
    iterations = 0
    while True:
        iterations += 1
        now = clock()
        if predicate():
            return True, now - start
        if now >= deadline or iterations > max_iterations:
            return False, now - start
        sleep(min(interval_s, max(0.0, deadline - now)))


def _unique_sorted_names(names: object) -> list[str] | None:
    """Sorted unique channel-name strings, or ``None`` if the input is malformed.

    Only collections of non-empty strings are channel names; anything else
    (including a missing measurement) is malformed and can never ground a
    coverage claim.
    """
    if not isinstance(names, (list, tuple, set, frozenset)):
        return None
    collected: list[str] = []
    for name in names:
        if not isinstance(name, str) or not name:
            return None
        collected.append(name)
    return sorted(set(collected))


def coverage_truth(
    configured_names: object,
    raw_observed_names: object,
) -> dict:
    """Honest producer coverage computed from channel NAMES, never counts.

    ``configured_names`` is the exact installed catalog (``ARKIT_CHANNELS``);
    ``raw_observed_names`` are the raw producer names this run observed live
    (the ``rc_shape_`` names in the consumer's ``_last_values``). The helper
    computes the intersection/difference itself, so a producer that emits an
    extra name (MediaPipe's ``_neutral``) or omits one (``tongueOut``) is
    reported as exactly what it is. Comparing ``len(raw)`` with
    ``len(configured)`` is structurally impossible here: the claim is derived
    from the catalog intersection only. The historical synthetic 52/52 target
    sweep is separate task evidence and never stands in for live producer
    coverage.
    """
    configured = _unique_sorted_names(configured_names)
    raw = _unique_sorted_names(raw_observed_names)
    catalog_set = set(configured or ())
    raw_set = set(raw or ())
    matched = sorted(catalog_set & raw_set)
    unexpected = sorted(raw_set - catalog_set)
    missing = sorted(catalog_set - raw_set)
    if configured is None or raw is None:
        claim = None
        note = (
            "malformed or unmeasured channel-name input; no producer coverage "
            "can be claimed from this report"
        )
    elif not configured:
        claim = None
        note = "the configured channel catalog is empty; coverage cannot be claimed"
    else:
        claim = f"live {len(matched)}/{len(configured)}"
        note = (
            "producer coverage measured live in this run from raw observed "
            "channel names; no synthetic target sweep is claimed by this run"
        )
    note += " The historical synthetic 52/52 target sweep is separate task evidence."
    return {
        "configured_channels": len(configured) if configured is not None else None,
        "configured_channel_names": configured,
        "raw_observed_channels": len(raw) if raw is not None else None,
        "raw_observed_channel_names": raw,
        "observed_catalog_channels": len(matched),
        "observed_catalog_channel_names": matched,
        "unexpected_channel_names": unexpected,
        "missing_configured_channel_names": missing,
        "producer_claim": claim,
        "note": note,
    }


def identity_failures(extension: dict) -> list[str]:
    """Failures for the installed-module identity block of the report."""
    failures: list[str] = []
    module = extension.get("module")
    if module != RC_EXTENSION_MODULE:
        failures.append(
            f"extension module identity is {module!r}; expected exactly "
            f"{RC_EXTENSION_MODULE!r}"
        )
    if extension.get("dev_module_refused") is not True:
        failures.append(
            f"the harness did not prove it refused the dev package "
            f"{DEV_PACKAGE_MODULE!r} as a substitute"
        )
    if extension.get("preferences_saved") is not False:
        failures.append(
            "preferences must never be saved; the report must record "
            "preferences_saved=False"
        )
    if extension.get("enabled_in_session") is not True:
        failures.append(
            "the extension was not proven enabled in-session"
        )
    return failures


def backend_failures(backend: dict) -> list[str]:
    """Failures for the backend-child block: started, real PID, reason, log."""
    failures: list[str] = []
    if backend.get("started") is not True:
        failures.append(
            "the backend child was not started by the installed extension "
            f"(reason: {backend.get('reason') or 'none recorded'})"
        )
    pid = backend.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        failures.append(f"the backend child pid is {pid!r}; a real pid is required")
    if not str(backend.get("reason") or "").strip():
        failures.append("the backend start reason was not recorded")
    if not str(backend.get("log_path") or "").strip():
        failures.append("the backend log path was not recorded")
    return failures


def lights_failures(dashboard: dict) -> list[str]:
    """Failures for the dashboard block: fresh snapshot, every light green."""
    failures: list[str] = []
    connections = dashboard.get("connections")
    if not isinstance(connections, list):
        failures.append(
            "the dashboard connections array is absent; absence is never green"
        )
        connections = []
    if dashboard.get("error"):
        failures.append(f"the dashboard status read failed: {dashboard['error']}")
    fetched_at = dashboard.get("fetched_at", 0.0)
    now_s = dashboard.get("now_s", 0.0)
    if not snapshot_is_fresh(fetched_at, now_s):
        failures.append(
            "the dashboard snapshot is absent or stale (fetched_at="
            f"{fetched_at!r}, age limit {MAX_SNAPSHOT_AGE_S:.1f} s); stale "
            "evidence is never green"
        )
    for light_id in LIGHT_IDS:
        light = light_by_id(connections, light_id)
        if light is None:
            failures.append(
                f"required dashboard light {light_id!r} is absent; absence is "
                "never green"
            )
        elif not light_is_green(light):
            failures.append(
                f"required dashboard light {light_id!r} is not green (state="
                f"{light.get('state')!r}, reason={light.get('reason')!r})"
            )
    return failures


def camera_to_rig_failures(live: dict) -> list[str]:
    """Failures for the camera-to-rig acquisition latency block.

    The block is a distinct fail-closed proof field, separate from the
    transport-only latency: it must exist, carry a positive integer count of
    valid camera samples, ZERO missing and ZERO invalid acquisition stamps,
    and finite non-negative latencies whose aggregates are coherent
    (``avg <= max <= session_max``). A sample count above the applied-packet
    total is an impossible measurement. This proves measurement AVAILABILITY
    and CONSISTENCY only; no roadmap threshold (such as 60 ms) is judged
    here — that decision owns a separate task.
    """
    failures: list[str] = []
    block = live.get("camera_to_rig")
    if not isinstance(block, dict):
        failures.append(
            "the camera_to_rig acquisition latency block is absent or "
            "malformed; absence is never green"
        )
        return failures
    samples = block.get("camera_samples")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        failures.append(
            f"camera_to_rig camera_samples is {samples!r}; a measured run "
            "requires a positive integer count of valid camera samples"
        )
    for field in ("missing_acq_stamps", "invalid_acq_stamps"):
        value = block.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            failures.append(
                f"camera_to_rig field {field!r} is {value!r}; an integer "
                "count is required"
            )
        elif value != 0:
            failures.append(
                f"camera_to_rig field {field!r} is {value!r}; a proven run "
                "requires zero unusable acquisition stamps"
            )
    latencies: dict[str, float] = {}
    for field in ("avg_camera_ms", "max_camera_ms", "session_max_camera_ms"):
        value = block.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            failures.append(
                f"camera_to_rig field {field!r} is {value!r}; a finite, "
                "non-negative latency measurement is required"
            )
        else:
            latencies[field] = float(value)
    if len(latencies) == 3:
        if latencies["avg_camera_ms"] > latencies["max_camera_ms"]:
            failures.append(
                "camera_to_rig aggregates are incoherent: avg_camera_ms "
                f"({latencies['avg_camera_ms']!r}) exceeds max_camera_ms "
                f"({latencies['max_camera_ms']!r})"
            )
        if latencies["max_camera_ms"] > latencies["session_max_camera_ms"]:
            failures.append(
                "camera_to_rig aggregates are incoherent: max_camera_ms "
                f"({latencies['max_camera_ms']!r}) exceeds "
                "session_max_camera_ms "
                f"({latencies['session_max_camera_ms']!r})"
            )
    applied = live.get("packets_applied")
    if (
        isinstance(samples, int)
        and not isinstance(samples, bool)
        and samples > 0
        and isinstance(applied, (int, float))
        and not isinstance(applied, bool)
        and samples > applied
    ):
        failures.append(
            f"camera_to_rig camera_samples ({samples!r}) exceeds the "
            f"applied-packet total ({applied!r}); an impossible measurement"
        )
    return failures


def live_failures(live: dict) -> list[str]:
    """Failures for the live-run block: progression, application, movement."""
    failures: list[str] = []
    samples = live.get("packet_samples")
    if not packets_progressing(samples):
        failures.append(f"packets did not progress (samples={samples!r})")
    applied = live.get("packets_applied")
    if isinstance(applied, bool) or not isinstance(applied, (int, float)) or applied <= 0:
        failures.append("no packets were applied by the consumer")
    movement = live.get("movement")
    if not isinstance(movement, dict) or movement.get("moved") is not True:
        failures.append(
            "the rig did not move: no actual rig target (non-Basis shape "
            "key) moved beyond the epsilon threshold"
        )
    elif not target_moved(movement.get("peak_deviations")):
        failures.append(
            "only controller, pose, or metadata values changed; no actual "
            "rig target (non-Basis shape key) deviation was recorded, so "
            "the movement gate is not met (metadata jitter is never movement)"
        )
    failures += camera_to_rig_failures(live)
    return failures


COVERAGE_NAME_FIELDS = (
    "configured_channel_names",
    "raw_observed_channel_names",
    "observed_catalog_channel_names",
    "unexpected_channel_names",
    "missing_configured_channel_names",
)

COVERAGE_COUNT_FIELDS = (
    "configured_channels",
    "raw_observed_channels",
    "observed_catalog_channels",
)


def catalog_digest(configured_names: object) -> str | None:
    """Deterministic SHA-256 over the sorted unique configured channel names.

    The names are newline-joined (no trailing newline) and hashed as UTF-8.
    Malformed input yields ``None``: absence is never a matching digest.
    """
    names = _unique_sorted_names(configured_names)
    if names is None:
        return None
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()


def coverage_failures(coverage: dict) -> list[str]:
    """Failures for the coverage block: a measured, honest producer claim.

    Every names list must exist, hold non-empty strings, and be duplicate
    free; every count must be a real integer; and every derived field must
    equal what the recorded names imply when recomputed — so an inflated
    claim, an impossible partition, or an inconsistent count cannot pass.
    Zero raw observations and zero catalog matches are never green, and the
    historical synthetic target sweep is separate task evidence, never part
    of this run's verdict.
    """
    failures: list[str] = []
    for field in COVERAGE_NAME_FIELDS:
        names = coverage.get(field)
        if not isinstance(names, list):
            failures.append(f"coverage field {field!r} is absent or not a name list")
        elif any(not isinstance(name, str) or not name for name in names):
            failures.append(f"coverage field {field!r} contains a non-name entry")
        elif len(set(names)) != len(names):
            failures.append(f"coverage field {field!r} contains duplicate names")
    for field in COVERAGE_COUNT_FIELDS:
        value = coverage.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            failures.append(f"coverage field {field!r} is absent or not a count")
    if failures:
        return failures
    # Every derived field must be exactly what the recorded names imply:
    # an inflated claim, a wrong count, or an impossible partition shows up
    # as an inconsistency, never as a judgement call.
    recomputed = coverage_truth(
        coverage["configured_channel_names"],
        coverage["raw_observed_channel_names"],
    )
    for field, expected in recomputed.items():
        if coverage.get(field) != expected:
            failures.append(
                f"coverage field {field!r} is inconsistent with the recorded "
                f"channel names (recorded {coverage.get(field)!r}; derived "
                f"{expected!r})"
            )
    if coverage["observed_catalog_channels"] == 0:
        if coverage["raw_observed_channels"] == 0:
            failures.append(
                "zero live producer channels were observed by this run; a run "
                "that observed no live channels is never green"
            )
        else:
            failures.append(
                "zero of the observed live producer names matched the "
                "configured channel catalog; a catalog-blind run is never green"
            )
    elif coverage["observed_catalog_channels"] < MINIMUM_LIVE_CATALOG_MATCHES:
        failures.append(
            f"only {coverage['observed_catalog_channels']} of "
            f"{coverage['configured_channels']} observed live producer names "
            f"matched the configured catalog; the known honest minimum for the "
            f"C4 MediaPipe contract is {MINIMUM_LIVE_CATALOG_MATCHES} of 52 "
            "(tongueOut is never emitted); a degraded producer is never green "
            "merely by being nonzero"
        )
    if coverage["configured_channels"] != EXPECTED_CONFIGURED_CHANNELS:
        failures.append(
            f"the configured channel catalog has "
            f"{coverage['configured_channels']} names; the C4 proof is defined "
            f"against exactly {EXPECTED_CONFIGURED_CHANNELS} names (the "
            "ARKit-52 vocabulary); a truncated or grown catalog cannot ground "
            "a producer claim"
        )
    if REQUIRED_CATALOG_SENTINEL not in coverage["configured_channel_names"]:
        failures.append(
            f"the configured channel catalog is missing "
            f"{REQUIRED_CATALOG_SENTINEL!r}; a catalog without it is not the "
            "ARKit-52 vocabulary even if it counts 52 names, and a count "
            "patched to match a degraded producer cannot ground a claim"
        )
    if FORBIDDEN_CATALOG_SENTINEL in coverage["configured_channel_names"]:
        failures.append(
            f"the configured channel catalog contains producer-only "
            f"{FORBIDDEN_CATALOG_SENTINEL!r}; producer artifacts belong to the "
            "raw observed names, never to the ARKit-52 configuration"
        )
    digest = catalog_digest(coverage["configured_channel_names"])
    if digest != EXPECTED_ARKIT_CATALOG_SHA256:
        failures.append(
            f"the configured channel catalog digest is {digest!r}; the C4 "
            f"proof requires the exact installed ARKit-52 vocabulary "
            f"(digest {EXPECTED_ARKIT_CATALOG_SHA256!r}); a same-size catalog "
            "with a swapped name is not this proof's configuration"
        )
    return failures


def cleanup_failures(cleanup: dict) -> list[str]:
    """Failures for the cleanup block: stopped, cleared, PID dead, ports free.

    Every item needs observed evidence. Missing evidence, unknown states,
    and stale checks are failures, never green.
    """
    failures: list[str] = []
    if cleanup.get("capture_stopped") is not True:
        failures.append("the capture stop was not confirmed (missing or refused)")
    stop = cleanup.get("backend_stop")
    if not isinstance(stop, dict) or stop.get("stopped") is not True:
        detail = stop.get("reason") if isinstance(stop, dict) else "no record"
        failures.append(f"the backend stop was not confirmed (missing or refused: {detail})")
    if cleanup.get("extension_state_cleared") is not True:
        failures.append("the extension state was not proven cleared after cleanup")
    pid = cleanup.get("pid_check")
    if not isinstance(pid, dict):
        failures.append(
            "the independent child-PID check is missing; absence is never green"
        )
    elif pid.get("alive") is True:
        failures.append(
            "the child PID is still alive after cleanup "
            f"(method={pid.get('method')!r})"
        )
    elif (
        pid.get("alive") is not False
        or not str(pid.get("method") or "").strip()
        or not str(pid.get("evidence") or "").strip()
    ):
        failures.append(
            "the child-PID death was not proven by an independent query "
            "(absent, unknown, or evidence-free)"
        )
    ports = cleanup.get("ports")
    if not isinstance(ports, dict):
        failures.append("the port release evidence is missing; absence is never green")
    else:
        for name in ("udp", "dashboard"):
            entry = ports.get(name)
            if (
                not isinstance(entry, dict)
                or entry.get("released") is not True
                or not str(entry.get("evidence") or "").strip()
            ):
                failures.append(
                    f"the {name} port release was not proven (held, unknown, "
                    "or evidence-free)"
                )
    return failures


def evaluate_proof(report: dict) -> list[str]:
    """The full verdict: every required proof failure, with exact reasons.

    An empty list means the C4 proof held. The runtime layer exits non-zero
    when this is non-empty; absence, staleness, and unknown states are never
    green because every check above demands positive observed evidence.
    """
    failures: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        failures.append(
            f"report schema is {report.get('schema')!r}; expected {REPORT_SCHEMA!r}"
        )
    failures += identity_failures(report.get("extension") or {})
    failures += backend_failures(report.get("backend") or {})
    failures += lights_failures(report.get("dashboard") or {})
    failures += live_failures(report.get("live") or {})
    failures += coverage_failures(report.get("coverage") or {})
    failures += cleanup_failures(report.get("cleanup") or {})
    return failures


def self_test() -> list[str]:
    """Pure self-checks of the verdict layer; runs without bpy.

    Returns the list of failures (empty means the verdict layer behaves).
    """
    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    expect(light_is_green({"state": "green"}), "green light not accepted")
    expect(not light_is_green({"state": "GREEN"}), "case-insensitive green accepted")
    expect(light_by_id([{"id": "camera"}], "camera") is not None, "light lookup broken")
    expect(not snapshot_is_fresh(0.0, 10.0), "never-fetched snapshot counted fresh")
    expect(snapshot_is_fresh(10.0, 10.0 + MAX_SNAPSHOT_AGE_S), "inclusive staleness broken")
    expect(packets_progressing([1, 2]), "progression rejected")
    expect(not packets_progressing([2, 2]), "static series accepted as progress")
    expect(target_moved({"shapekey::jawOpen": 0.5}), "target movement rejected")
    expect(not target_moved({"rc_meta_conf": 0.9, "rc_shape_jawOpen": 0.7}),
           "controller/metadata jitter counted as rig movement")
    expect(not target_moved({"shapekey::Basis": 0.9}), "Basis counted as a target")
    expect(live_shape_channel_names(
        {"rc_shape_jawOpen", "rc_pose_rx", "rc_meta_conf"}) == ["jawOpen"],
        "live channels polluted by pose/metadata keys")
    expect(not live_shape_channel_names(set()), "an empty run produced channels")
    expect(operator_finished({"FINISHED"}), "FINISHED not accepted")
    expect(operator_finished(frozenset({"FINISHED"})),
           "frozenset FINISHED not accepted")
    expect(not operator_finished("{'FINISHED'}"),
           "str(set) accepted as an operator result")
    expect(not operator_finished({"CANCELLED"}), "CANCELLED accepted as finished")
    catalog = list(_SELF_TEST_CATALOG)
    raw = list(_SELF_TEST_RAW)
    truth = coverage_truth(catalog, raw)
    expect(truth["producer_claim"] == "live 51/52",
           "honest 51/52 coverage claim broken")
    expect(truth["unexpected_channel_names"] == ["_neutral"],
           "the unexpected-name field is wrong")
    expect(truth["missing_configured_channel_names"] == ["tongueOut"],
           "the missing-name field is wrong")
    expect(truth["raw_observed_channels"] == 52 and truth["observed_catalog_channels"] == 51,
           "raw and catalog counts are conflated")
    expect(not coverage_failures(truth), "honest 51/52 coverage failed the verdict")
    zero = coverage_truth(catalog, [])
    expect(any("zero" in f for f in coverage_failures(zero)),
           "zero observed live channels was not a failure")
    blind = coverage_truth(catalog, ["_neutral", "notAChannel"])
    expect(any("zero" in f for f in coverage_failures(blind)),
           "zero catalog matches was not a failure")
    inflated = dict(truth, producer_claim="live 52/52")
    expect(coverage_failures(inflated), "an inflated producer claim was accepted")
    partition = dict(truth, observed_catalog_channels=52)
    expect(coverage_failures(partition), "an impossible partition was accepted")
    duplicated = dict(truth, raw_observed_channel_names=raw + [raw[0]])
    expect(any("duplicate" in f for f in coverage_failures(duplicated)),
           "duplicate channel names were accepted")
    truncated = coverage_truth(
        ["jawOpen", "mouthPucker", "tongueOut"],
        ["jawOpen", "mouthPucker", "tongueOut"],
    )
    expect(any("52" in f for f in coverage_failures(truncated)),
           "a truncated configured catalog was accepted")
    degraded = coverage_truth(
        catalog, sorted(set(catalog) - {"tongueOut"})[:40] + ["_neutral"]
    )
    expect(any("51" in f for f in coverage_failures(degraded)),
           "a producer degraded below the minimum was accepted")
    full = coverage_truth(catalog, catalog)
    expect(coverage_failures(full) == [],
           "full 52/52 coverage failed the verdict")
    expect(coverage_failures(truth) == [],
           "the known honest 51/52 contract failed the verdict")
    no_tongue = coverage_truth(
        sorted((set(catalog) - {"tongueOut"}) | {"fakeBlink"}),
        sorted((set(catalog) - {"tongueOut"}) | {"fakeBlink"})[:-1],
    )
    expect(any("tongueOut" in f for f in coverage_failures(no_tongue)),
           "a tongueOut-less 52-name catalog was accepted")
    neutral_config = sorted((set(catalog) - {catalog[0]}) | {"_neutral"})
    polluted = coverage_truth(neutral_config, neutral_config)
    expect(any("_neutral" in f for f in coverage_failures(polluted)),
           "a _neutral-polluted 52-name catalog was accepted")
    swapped = sorted((set(catalog) - {catalog[0]}) | {"fakeBlink"})
    swapped_truth = coverage_truth(swapped, swapped)
    expect(any("digest" in f for f in coverage_failures(swapped_truth)),
           "a non-sentinel name swap passed exact catalog identity")
    expect(catalog_digest(catalog) == EXPECTED_ARKIT_CATALOG_SHA256,
           "the self-test catalog is not the exact ARKit-52 vocabulary")
    ok, elapsed = wait_until(
        lambda: True, 1.0, clock=lambda: 0.0, sleep=lambda _s: None
    )
    expect(ok and elapsed == 0.0, "immediate predicate not accepted")
    frozen_ok, _ = wait_until(
        lambda: False, 0.5, 0.25, clock=lambda: 0.0, sleep=lambda _s: None
    )
    expect(not frozen_ok, "a frozen injected clock was treated as success")
    deviations = movement_from_samples(
        {"rc_shape_jawOpen": 0.0},
        [{"rc_shape_jawOpen": 0.0}, {"rc_shape_jawOpen": 0.7},
         {"rc_shape_jawOpen": 0.0}],
    )
    expect(window_moved(deviations), "a mid-window spike was not accumulated")
    expect(not window_moved({"a": 0.0}), "zero deviation counted as movement")
    expect(coverage_truth(catalog, None)["producer_claim"] is None,
           "unmeasured coverage produced a claim")
    expect(evaluate_proof(_self_test_report()) == [], "healthy self-test report failed")
    mutated = _self_test_report()
    mutated["cleanup"]["pid_check"]["alive"] = True
    expect(evaluate_proof(mutated), "alive PID not caught")
    unmeasured = _self_test_report()
    del unmeasured["live"]["camera_to_rig"]
    expect(any("camera_to_rig" in f for f in evaluate_proof(unmeasured)),
           "an absent camera_to_rig block was accepted")
    zero_samples = _self_test_report()
    zero_samples["live"]["camera_to_rig"]["camera_samples"] = 0
    expect(any("camera_samples" in f
               for f in evaluate_proof(zero_samples)),
           "zero camera samples were accepted")
    unusable = _self_test_report()
    unusable["live"]["camera_to_rig"]["invalid_acq_stamps"] = 1
    expect(any("invalid_acq_stamps" in f
               for f in evaluate_proof(unusable)),
           "an invalid acquisition stamp was accepted")
    incoherent = _self_test_report()
    incoherent["live"]["camera_to_rig"]["max_camera_ms"] = 99.0
    expect(any("incoherent" in f for f in evaluate_proof(incoherent)),
           "incoherent camera latency aggregates were accepted")
    return failures


def _self_test_report() -> dict:
    """A minimal healthy report for the pure self-test (no bpy, no files)."""
    return {
        "schema": REPORT_SCHEMA,
        "extension": {
            "module": RC_EXTENSION_MODULE,
            "dev_module_refused": True,
            "preferences_saved": False,
            "enabled_in_session": True,
        },
        "backend": {"started": True, "pid": 1, "reason": "r", "log_path": "l"},
        "dashboard": {
            "connections": [
                {"id": light_id, "state": "green", "reason": "ok"}
                for light_id in LIGHT_IDS
            ],
            "fetched_at": 1.0,
            "now_s": 1.1,
            "error": None,
        },
        "live": {
            "packet_samples": [1, 2],
            "packets_applied": 2,
            "camera_to_rig": {
                "camera_samples": 2,
                "missing_acq_stamps": 0,
                "invalid_acq_stamps": 0,
                "avg_camera_ms": 33.0,
                "max_camera_ms": 34.0,
                "session_max_camera_ms": 34.0,
            },
            "movement": {
                "moved": True,
                "peak_deviations": {"shapekey::jawOpen": 0.5},
                "target_deviations": {"shapekey::jawOpen": 0.5},
            },
        },
        "coverage": dict(coverage_truth(_SELF_TEST_CATALOG, _SELF_TEST_RAW)),
        "cleanup": {
            "capture_stopped": True,
            "backend_stop": {"stopped": True, "reason": "stopped"},
            "extension_state_cleared": True,
            "pid_check": {"alive": False, "method": "tasklist", "evidence": "no tasks"},
            "ports": {
                "udp": {"released": True, "evidence": "bind ok"},
                "dashboard": {"released": True, "evidence": "bind+listen ok"},
            },
        },
    }


# -- bpy runtime layer (every bpy import is lazy and inside a function) --------------


def _import_bpy():
    try:
        import bpy  # noqa: PLC0415 - lazy by contract
    except ImportError as exc:
        raise ProofError("bpy is not available: run this harness inside Blender") from exc
    return bpy


def _installed_ui():
    """The installed extension's ui module, which owns the child-process handle."""
    module = sys.modules.get(RC_EXTENSION_MODULE)
    ui = getattr(module, "ui", None)
    if ui is None:
        raise ProofError(
            f"the installed extension module {RC_EXTENSION_MODULE!r} is not loaded"
        )
    return ui


def resolve_installed_module() -> dict:
    """Prove the installed extension identity; refuse the dev ``addon`` package.

    Enables the extension only in-session if needed. Never saves preferences.
    Returns the identity block for the report.
    """
    bpy = _import_bpy()
    addons = set(bpy.context.preferences.addons.keys())
    if DEV_PACKAGE_MODULE in addons:
        raise ProofError(
            f"dev package {DEV_PACKAGE_MODULE!r} is enabled in this Blender "
            f"session; refusing to substitute it for the installed "
            f"{RC_EXTENSION_MODULE!r}"
        )
    enabled_in_session = RC_EXTENSION_MODULE in addons
    if not enabled_in_session:
        import addon_utils  # noqa: PLC0415 - Blender-only, lazy

        addon_utils.enable(RC_EXTENSION_MODULE, default_set=True, persistent=False)
        addons = set(bpy.context.preferences.addons.keys())
        if RC_EXTENSION_MODULE not in addons:
            raise ProofError(
                f"could not enable {RC_EXTENSION_MODULE!r} in-session; is the "
                "extension installed in user_default?"
            )
    return {
        "module": RC_EXTENSION_MODULE,
        "dev_module_refused": True,
        "preferences_saved": False,
        "enabled_in_session": True,
        "was_already_enabled": enabled_in_session,
    }


def _installed_preferences(bpy) -> dict:  # noqa: ANN001 - bpy module
    entry = bpy.context.preferences.addons.get(RC_EXTENSION_MODULE)
    if entry is None or getattr(entry, "preferences", None) is None:
        raise ProofError(
            f"the installed extension {RC_EXTENSION_MODULE!r} has no preferences"
        )
    return entry.preferences


def configure_temporary_preferences(
    repo_root: str, udp_port: int, dashboard_port: int, camera_index: int
) -> dict:
    """Set this session's temporary preferences; never save them.

    The venv interpreter is left empty so the installed cockpit derives
    ``<repo_root>/backend/.venv/Scripts/python.exe`` itself. Returns the
    recorded preference block for the report.
    """
    bpy = _import_bpy()
    prefs = _installed_preferences(bpy)
    prefs.repo_root = repo_root
    prefs.python_executable = ""
    prefs.udp_port = udp_port
    prefs.dashboard_port = dashboard_port
    prefs.camera_index = camera_index
    prefs.open_browser_on_start = False
    scene_settings = bpy.context.scene.realcapture
    scene_settings.udp_port = udp_port  # sync scene UDP with the preference
    return {
        "repo_root": repo_root,
        "python_executable": "(derived from repo_root)",
        "udp_port": udp_port,
        "dashboard_port": dashboard_port,
        "camera_index": camera_index,
        "open_browser_on_start": False,
        "preferences_saved": False,
    }


def find_rig_and_bind() -> dict:
    """Find the rig, create/select the controller, run the installed wizard.

    Records shape/bone counts, whether the bone path is active, and the
    rest-gate skip reason verbatim.
    """
    bpy = _import_bpy()
    context = bpy.context
    settings = context.scene.realcapture

    face_mesh = _find_face_mesh(bpy)
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if face_mesh is None:
        raise ProofError("no mesh with shape keys was found in the blend")
    settings.rig_face_mesh = face_mesh
    settings.rig_armature = armature

    controller = bpy.data.objects.get("RealCapture_Controller")
    if controller is None:
        controller = bpy.data.objects.new("RealCapture_Controller", None)
        context.scene.collection.objects.link(controller)
    settings.controller = controller
    context.view_layer.objects.active = controller
    controller.select_set(True)

    if bpy.ops.realcapture.scan_rig() != {"FINISHED"}:
        raise ProofError("the installed realcapture.scan_rig operator did not finish")
    proposals = len(settings.rig_proposals)
    if bpy.ops.realcapture.bind_rig() != {"FINISHED"}:
        raise ProofError("the installed realcapture.bind_rig operator did not finish")

    ui = _installed_ui()
    consumer = ui._get_consumer()
    rig = consumer.face_points
    report_obj = getattr(rig, "bind_report", None)
    shape_entries = getattr(rig, "_shape_entries", []) if rig is not None else []
    shape_channels = len({entry["channel"] for entry in shape_entries})
    bone_names = (
        [bone.name for bone in armature.data.bones] if armature is not None else []
    )
    return {
        "face_mesh": face_mesh.name,
        "armature": armature.name if armature is not None else None,
        "shape_keys": len(face_mesh.data.shape_keys.key_blocks) - 1
        if face_mesh.data.shape_keys else 0,
        "bones": len(bone_names),
        "scan_proposals": proposals,
        "shape_channels_bound": shape_channels,
        "bone_path_active": bool(report_obj.bone_path_active) if report_obj else False,
        "rest_gate_skip_reason": getattr(report_obj, "skip_reason", None),
        "rest_displacement_m": getattr(report_obj, "rest_displacement", None),
    }


def _find_face_mesh(bpy):  # noqa: ANN001 - bpy module
    """The mesh most likely to be the face: the most shape keys wins."""
    candidates = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH" and obj.data.shape_keys
        and len(obj.data.shape_keys.key_blocks) > 1
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda obj: len(obj.data.shape_keys.key_blocks))


def start_backend_via_operator() -> dict:
    """Invoke the installed start_backend operator and record the child truth."""
    bpy = _import_bpy()
    ui = _installed_ui()
    prefs = _installed_preferences(bpy)
    scene_udp = getattr(bpy.context.scene.realcapture, "udp_port", None)
    settings = ui.cockpit.settings_from_preferences(prefs, scene_udp_port=scene_udp)
    paths = settings.paths()
    argv = settings.argv()

    if bpy.ops.realcapture.start_backend() != {"FINISHED"}:
        raise ProofError("the installed realcapture.start_backend operator failed")

    process = ui._process
    block = {
        "started": bool(process.started) if process is not None else False,
        "pid": process.pid if process is not None else None,
        "reason": process.reason if process is not None else
        "no process handle existed after start_backend",
        "log_path": str(paths.log_path),
        "argv": argv,
    }
    return block


def poll_dashboard_status(dashboard_port: int, timeout_s: float = 10.0) -> dict:
    """Poll ``/api/status`` through the installed reader until it answers."""
    ui = _installed_ui()
    fetch = ui.dashboard_client.fetch_status
    result: dict = {"connections": [], "fetched_at": 0.0, "now_s": 0.0, "error": None}

    def try_fetch() -> bool:
        try:
            payload = fetch(dashboard_port, timeout_s=1.5)
        except Exception as exc:  # noqa: BLE001 - a failed read is recorded, not raised
            result["error"] = str(exc) or type(exc).__name__
            return False
        result["connections"] = payload.get("connections", [])
        result["fetched_at"] = time.monotonic()
        result["now_s"] = result["fetched_at"]
        result["error"] = None
        return True

    ok, elapsed = wait_until(try_fetch, timeout_s=timeout_s, interval_s=0.25)
    result["poll_seconds"] = elapsed
    result["answered"] = ok
    return result


def start_capture_via_operator() -> dict:
    """Invoke the installed start_capture operator (consumer + recorder)."""
    bpy = _import_bpy()
    if bpy.ops.realcapture.start_capture() != {"FINISHED"}:
        raise ProofError("the installed realcapture.start_capture operator failed")
    return {"capture_started": True}


def pump_consumer(duration_s: float) -> dict:
    """Manually pump the installed consumer's ``_tick()`` for a bounded time.

    bpy.app.timers do not fire in background mode, so the harness pumps at
    ~60 Hz exactly like tools/blender_soak.py. The packets are the REAL
    backend's (it owns camera 0); no synthetic sender exists in real mode.
    Movement and target deviations ACCUMULATE over the whole window: a value
    that spiked mid-window and returned to baseline still counts (see
    ``movement_from_samples``), and the movement gate is satisfied only by
    non-Basis shape-key (``shapekey::``) deviations — controller/pose/meta
    changes are recorded as diagnostics but can never green it. Observed
    live channels come from the consumer's ``_last_values`` (cleared at
    ``_begin``), i.e. exactly the ``rc_shape_`` data THIS run wrote.
    """
    bpy = _import_bpy()
    ui = _installed_ui()
    consumer = ui._get_consumer()
    if not consumer.running:
        raise ProofError("the installed consumer is not running; start_capture failed")
    consumer._timer_registered = True  # manual pump keeps _tick alive

    controller = bpy.context.scene.realcapture.controller
    face_mesh = bpy.context.scene.realcapture.rig_face_mesh
    props_before = _controller_props(controller)
    keys_before = _shape_key_values(face_mesh)
    baseline = {
        **props_before,
        **{f"shapekey::{name}": value for name, value in keys_before.items()},
    }

    samples: list[dict] = []
    transport: dict = {}

    def take_sample() -> dict:
        # Driven shape-key values are refreshed by the depsgraph; make the
        # view layer current before reading the rig targets.
        bpy.context.view_layer.update()
        merged = {
            **_controller_props(controller),
            **{f"shapekey::{name}": value
               for name, value in _shape_key_values(face_mesh).items()},
        }
        samples.append(merged)
        return merged

    started = time.perf_counter()
    ticks = 0
    applied_at_start = consumer.stats.packets_applied
    packet_samples: list[float] = []
    next_sample = 0.0
    while True:
        loop_start = time.perf_counter()
        elapsed = loop_start - started
        if elapsed >= duration_s:
            break
        consumer._tick()
        ticks += 1
        if elapsed >= next_sample:
            packet_samples.append(float(consumer.stats.packets_applied))
            take_sample()
            next_sample += 1.0
        sleep_for = (1.0 / 60.0) - (time.perf_counter() - loop_start)
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            time.sleep(0.0005)

    stats = consumer.stats
    props_after = _controller_props(controller)
    keys_after = _shape_key_values(face_mesh)
    final_sample = take_sample()  # always close the window with a final sample
    deviations = movement_from_samples(baseline, samples)
    target_deviations = {
        key: value for key, value in deviations.items()
        if key.startswith(RIG_TARGET_PREFIX)
    }
    # Raw observed producer channel NAMES: the exact rc_shape_ keys the
    # consumer wrote during THIS run (_last_values is cleared at _begin),
    # never pre-existing controller props, pose keys, or metadata. These are
    # raw names — coverage against the configured catalog is computed later
    # by coverage_truth, never by comparing counts.
    observed_names = live_shape_channel_names(
        set(getattr(consumer, "_last_values", None) or ())
    )
    changed = {
        key: value for key, value in props_after.items()
        if props_before.get(key) != value
    }
    keys_changed = {
        key: value for key, value in keys_after.items()
        if keys_before.get(key) != value
    }
    transport = {
        "avg_ms": stats.avg_transport_ms,
        "max_ms": stats.max_transport_ms,
        "applied_fps": stats.applied_fps,
        "engine": stats.engine,
    }

    # Camera-to-rig acquisition latency: a distinct fail-closed proof field,
    # recorded from the FINAL post-pump stats as JSON-safe primitives (None
    # only when a latency was never measurable; the verdict fails closed on
    # that when valid samples exist). The transport block above stays
    # transport-only. No roadmap threshold is judged here: this proves
    # measurement availability and consistency, not the threshold owner.
    camera_to_rig = {
        "camera_samples": int(stats.camera_samples),
        "missing_acq_stamps": int(stats.missing_acq_stamps),
        "invalid_acq_stamps": int(stats.invalid_acq_stamps),
        "avg_camera_ms": _json_latency(stats.avg_camera_ms),
        "max_camera_ms": _json_latency(stats.max_camera_ms),
        "session_max_camera_ms": _json_latency(stats.session_max_camera_ms),
    }
    return {
        "pump_seconds": duration_s,
        "ticks": ticks,
        "packets_applied": stats.packets_applied - applied_at_start,
        "packet_samples": packet_samples,
        "transport": transport,
        "camera_to_rig": camera_to_rig,
        "props_before": props_before,
        "props_after": props_after,
        "controller_changed": changed,  # diagnostics only
        "shape_keys_changed": keys_changed,  # diagnostics only
        "movement": {
            "moved": target_moved(deviations),  # actual rig targets only
            "peak_deviations": deviations,
            "target_deviations": target_deviations,
            "final_changed": final_sample,
        },
        "raw_observed_channels": len(observed_names),
        "raw_observed_channel_names": observed_names,
    }


def _json_latency(value: object) -> float | None:
    """A JSON-safe latency primitive, or ``None`` when never measurable."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return None
    return float(value)


def _controller_props(controller) -> dict:  # noqa: ANN001 - bpy Object
    if controller is None:
        return {}
    return {
        key: value for key, value in controller.items()
        if key.startswith(("rc_shape_", "rc_pose_", "rc_meta_"))
        and isinstance(value, (int, float))
    }


def _shape_key_values(face_mesh) -> dict:  # noqa: ANN001 - bpy Object
    if face_mesh is None or face_mesh.data.shape_keys is None:
        return {}
    return {
        block.name: block.value
        for block in face_mesh.data.shape_keys.key_blocks
        if block.name != "Basis"
    }


# -- cleanup truth --------------------------------------------------------------------


def pid_alive_independently(pid: int | None) -> dict:
    """Independent Windows query of the child PID; never the child's own handle.

    Uses ``tasklist`` (Windows) or ``ps`` (POSIX). Returns the method, the
    alive verdict, and the raw output as evidence. An unknown answer is
    reported as unknown, never as dead.
    """
    if not isinstance(pid, int) or pid <= 0:
        return {"alive": None, "method": "none", "evidence": "no pid to check"}
    if sys.platform == "win32":
        method = "tasklist"
        command = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    else:
        method = "ps"
        command = ["ps", "-p", str(pid)]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, shell=False, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"alive": None, "method": method, "evidence": f"query failed: {exc}"}
    raw = ((completed.stdout or "") + (completed.stderr or "")).strip()
    alive = str(pid) in raw
    return {"alive": alive, "method": method, "evidence": raw}


def _dashboard_release_probe(dashboard_port: int) -> dict:
    """Bind+listen probe: success proves the dashboard port is released.

    A fresh TCP socket with NO address reuse binds the exact
    ``127.0.0.1:<port>`` and listens. On Windows ``SO_EXCLUSIVEADDRUSE``
    prevents another process's address-reuse socket from sharing the port,
    so a success here is positive release evidence. This never uses
    ``connect()``: this host's firewall drops loopback SYNs to closed ports,
    so a connect to a RELEASED port times out, and a timeout is never
    release evidence.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if sys.platform == "win32" and exclusive is not None:
            probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        probe.bind(("127.0.0.1", dashboard_port))
        probe.listen(1)
        return {
            "released": True,
            "evidence": f"bind+listen 127.0.0.1:{dashboard_port} succeeded",
        }
    except OSError as exc:
        return {
            "released": False,
            "evidence": f"bind+listen 127.0.0.1:{dashboard_port} failed: {exc}",
        }
    finally:
        probe.close()


def port_release_truth(udp_port: int, dashboard_port: int) -> dict:
    """Prove both ports are released by actually trying to bind them.

    UDP: a successful bind proves release; a failed bind is held. Dashboard
    TCP: a successful fresh bind+listen proves release; any bind failure is
    held and the verdict treats anything but ``released: True`` as a
    failure. No ``connect()`` is used, so no timeout can ever be mistaken
    for release.
    """
    ports: dict = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", udp_port))
        ports["udp"] = {
            "released": True, "evidence": f"bind 127.0.0.1:{udp_port} succeeded",
        }
    except OSError as exc:
        ports["udp"] = {
            "released": False, "evidence": f"bind 127.0.0.1:{udp_port} failed: {exc}",
        }
    finally:
        sock.close()
    ports["dashboard"] = _dashboard_release_probe(dashboard_port)
    return ports


def run_cleanup(bpy) -> dict:  # noqa: ANN001 - bpy module
    """Always-run cleanup through the installed operators, plus the truth check.

    Stop capture and stop backend each run EXACTLY ONCE, through the
    installed operators (the stop_backend operator owns the BackendProcess
    tree kill; the harness never stops that process object directly, so the
    child can never be double-stopped or half-stopped). Stop truth is
    derived from the operator results, the cleared extension state, and an
    independent bounded PID-death check; the PID and port release waits are
    bounded like every other wait in this harness.
    """
    cleanup: dict = {}
    ui = None
    try:
        ui = _installed_ui()
    except ProofError:
        pass

    process = getattr(ui, "_process", None) if ui is not None else None
    pid = process.pid if process is not None else None
    reason_before = process.reason if process is not None else ""

    # stop capture first (consumer timer), then the backend child (tree kill):
    # each operator exactly once, never a direct BackendProcess stop here.
    # The exact result objects decide stop truth; the JSON record holds a
    # separate representation (str(set) comparison is never used).
    capture_result: object = None
    capture_op: str
    try:
        capture_result = bpy.ops.realcapture.stop_capture()
    except Exception as exc:  # noqa: BLE001 - record, never hide
        capture_op = f"failed: {exc}"
    else:
        capture_op = operator_repr(capture_result)
    cleanup["capture_stop_operator"] = capture_op
    backend_result: object = None
    backend_op: str
    try:
        backend_result = bpy.ops.realcapture.stop_backend()
    except Exception as exc:  # noqa: BLE001 - record, never hide
        backend_op = f"failed: {exc}"
    else:
        backend_op = operator_repr(backend_result)
    cleanup["backend_stop_operator"] = backend_op

    consumer = ui._get_consumer() if ui is not None else None
    scene_enabled = getattr(bpy.context.scene.realcapture, "enabled", None)
    consumer_running = bool(consumer.running) if consumer is not None else None
    process_after = getattr(ui, "_process", None) if ui is not None else "missing"
    cleanup["state_observed"] = {
        "scene_enabled": scene_enabled,
        "consumer_running": consumer_running,
        "process_handle": "present" if process_after else "none",
    }
    state_cleared = bool(
        scene_enabled is False
        and consumer_running is False
        and not process_after
    )
    cleanup["extension_state_cleared"] = state_cleared

    # Bounded independent PID-death wait: the child's own handle is never
    # trusted for this; only the independent OS query is evidence.
    if pid is not None:
        dead, elapsed = wait_until(
            lambda: pid_alive_independently(pid)["alive"] is False,
            timeout_s=10.0, interval_s=0.5,
        )
        pid_check = pid_alive_independently(pid)
        pid_check["confirmed_within_wait"] = dead
        pid_check["wait_seconds"] = elapsed
    else:
        pid_check = {
            "alive": None, "method": "none",
            "evidence": "no child pid was recorded by this session",
        }
    cleanup["pid_check"] = pid_check

    # Bounded port release wait; the final truth is recorded as observed.
    scene_settings = getattr(bpy.context.scene, "realcapture", None)
    udp_port = int(
        getattr(scene_settings, "udp_port", DEFAULT_UDP_PORT) or DEFAULT_UDP_PORT
    )
    dashboard_port = int(
        getattr(_prefs_dashboard_port(bpy), "dashboard_port", DEFAULT_DASHBOARD_PORT)
        or DEFAULT_DASHBOARD_PORT
    )

    def ports_free() -> bool:
        truth = port_release_truth(udp_port, dashboard_port)
        return all(entry.get("released") is True for entry in truth.values())

    released, ports_wait = wait_until(ports_free, timeout_s=5.0, interval_s=0.5)
    cleanup["ports"] = port_release_truth(udp_port, dashboard_port)
    cleanup["ports_released_within_wait"] = released
    cleanup["ports_wait_seconds"] = ports_wait

    # Stop truth is derived: exact operator results + cleared state + PID
    # evidence. A str(set) comparison or any other repr accident never
    # decides anything here.
    cleanup["capture_stopped"] = bool(
        operator_finished(capture_result) and consumer_running is False
    )
    cleanup["backend_stop"] = {
        "stopped": bool(
            operator_finished(backend_result)
            and state_cleared
            and pid_check.get("alive") is False
        ),
        "reason": (
            f"operator={backend_op}; state_cleared={state_cleared}; "
            f"reason_before_stop={reason_before or 'none'}"
        ),
        "exit_code": None,
    }
    return cleanup


def _prefs_dashboard_port(bpy):  # noqa: ANN001 - bpy module
    try:
        return _installed_preferences(bpy)
    except ProofError:
        return {}


# -- CLI and main ----------------------------------------------------------------------


def parse_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="blender_start_proof",
        description="Bounded proof harness for the installed RealCapture extension (C4).",
    )
    parser.add_argument("--self-test", action="store_true",
                        help="run the pure verdict self-test without Blender")
    parser.add_argument("--blend", help="character .blend to open")
    parser.add_argument("--repo-root", default=os.environ.get("RC_REPO_ROOT", ""),
                        help="RealCapture repository root (default: $RC_REPO_ROOT)")
    parser.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT)
    parser.add_argument("--dashboard-port", type=int, default=DEFAULT_DASHBOARD_PORT)
    parser.add_argument("--camera", type=int, default=DEFAULT_CAMERA_INDEX)
    parser.add_argument("--duration", type=float, default=DEFAULT_PUMP_SECONDS,
                        help="bounded pump duration in seconds")
    parser.add_argument("--report", help="JSON report path (default: OS temp folder)")
    parser.add_argument("--backend-timeout", type=float, default=30.0,
                        help="bounded wait for the backend dashboard to answer")
    return parser.parse_args(argv)


def _cli_args() -> list[str]:
    """Arguments after ``--`` under Blender, or sys.argv[1:] under plain Python."""
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return sys.argv[1:]


def default_report_path() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"realcapture_start_proof_{int(time.time())}.json",
    )


def write_report(report: dict, path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=False)
        fh.write("\n")
    return path


def run_proof(args: argparse.Namespace, report: dict) -> None:
    """The bpy-side proof; every wait bounded, every reason recorded."""
    bpy = _import_bpy()
    if not args.repo_root.strip():
        raise ProofError(
            "no repository root: pass --repo-root or set RC_REPO_ROOT"
        )
    if not args.blend:
        raise ProofError("no --blend character file was given")
    if not os.path.isfile(args.blend):
        raise ProofError(f"the character blend does not exist: {args.blend}")

    bpy.ops.wm.open_mainfile(filepath=args.blend)
    report["blend_path"] = args.blend
    report["blender_version"] = tuple(bpy.app.version)
    report["extension"] = resolve_installed_module()
    report["preferences"] = configure_temporary_preferences(
        args.repo_root, args.udp_port, args.dashboard_port, args.camera
    )
    report["rig"] = find_rig_and_bind()

    report["backend"] = start_backend_via_operator()
    # The pre-capture snapshot is preserved separately for diagnostics; the
    # VERDICT only ever reads the FINAL snapshot fetched after the pump, so
    # the Blender heartbeat light is judged on post-run evidence, never on a
    # pre-capture state that cannot show a live heartbeat.
    report["dashboard_initial"] = poll_dashboard_status(
        args.dashboard_port, timeout_s=args.backend_timeout
    )
    report["capture"] = start_capture_via_operator()
    report["live"] = pump_consumer(max(0.0, args.duration))
    report["dashboard"] = poll_dashboard_status(
        args.dashboard_port, timeout_s=args.backend_timeout
    )

    # The configured catalog NAMES come from the exact installed module path,
    # imported via importlib; package-level attribute lookups are never used
    # because the installed package __init__ must not be trusted for this.
    configured_names: list[str] | None
    try:
        channels_module = importlib.import_module(
            f"{RC_EXTENSION_MODULE}.rigprofile.channels"
        )
        channels = getattr(channels_module, "ARKIT_CHANNELS", None)
        configured_names = (
            [str(name) for name in channels]
            if isinstance(channels, tuple) and channels else None
        )
    except Exception:  # noqa: BLE001 - an unimportable catalog is a verdict failure
        configured_names = None
    # Coverage is computed from NAMES: the exact installed catalog versus the
    # raw producer names this run observed (consumer._last_values via the
    # live block). A 52-name raw list with one extra name and one absent
    # ARKit name reports live 51/52, never an inflated 52/52.
    report["coverage"] = coverage_truth(
        configured_names, report["live"].get("raw_observed_channel_names")
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_cli(argv if argv is not None else _cli_args())
    if args.self_test:
        failures = self_test()
        for failure in failures:
            print(f"SELF-TEST FAILED: {failure}", flush=True)
        print(
            "self-test passed: the pure verdict layer behaves"
            if not failures else "self-test FAILED",
            flush=True,
        )
        return 1 if failures else 0

    report: dict = {"schema": REPORT_SCHEMA}
    failures: list[str]
    try:
        run_proof(args, report)
    except ProofError as exc:
        report["fatal"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - record the crash, still clean up
        report["fatal"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            report["cleanup"] = run_cleanup(_import_bpy())
        except Exception as exc:  # noqa: BLE001 - a cleanup crash is still recorded
            report["cleanup"] = {"cleanup_crashed": f"{type(exc).__name__}: {exc}"}
        failures = evaluate_proof(report)
        report["verdict"] = {"ok": not failures, "failures": failures}
        path = write_report(report, args.report or default_report_path())

    print("=== RealCapture start proof report ===", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    print(f"report written to: {path}", flush=True)
    if failures:
        for failure in failures:
            print(f"PROOF FAILED: {failure}", flush=True)
        return 1
    print("PROOF HELD: every required check passed", flush=True)
    return 0


if __name__ == "__main__":
    code = 2
    try:
        code = main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - never exit zero by accident
        import traceback  # noqa: PLC0415

        traceback.print_exc()
        print("HARNESS CRASHED", flush=True)
        code = 2
    sys.exit(code)

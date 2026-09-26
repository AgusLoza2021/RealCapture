"""Connection-status model: raw facts in, traffic lights out (pure logic).

This module is deliberately free of FastAPI, bpy, cv2 and numpy, and must
never import ``addon/`` (that package pulls in bpy). Sources arrive as plain
values; ``DashboardHub`` injects them from its injected callables.

The truth table (see odd/tasks/control-room-window.md, "Frozen contract"):

- two thresholds per signal: green at or under FRESH, yellow up to STALE,
  red beyond STALE. An absent or unknown signal (age ``None``) is red with
  a reason, never green — nothing goes green because nothing told it
  otherwise.
- the Blender light judges the bind IN EFFECT, never a point/bone attempt
  that the rest gate refused: ``rest_displacement_m`` is the bind in effect
  and ``refused_rest_displacement_m`` is the rejected attempt, travelled
  separately. Reporting the refused number as the bind's health would paint
  a perfectly working shape-keys bind yellow forever, and a permanent false
  alarm costs exactly what a false green costs.
- a refused bone path with a working fallback is the gate doing its job, not
  a fault: it belongs in an informational green reason, not in the colour.

A light with a state other than green and an empty reason is a programming
error: the single constructor below raises instead of silently cleaning it
up into something plausible. Proven by mutation test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

GREEN = "green"
YELLOW = "yellow"
RED = "red"

#: Camera frame age thresholds, in seconds (fresh / stale).
CAMERA_FRESH_S = 1.0
CAMERA_STALE_S = 2.0

#: Packets-to-Blender last-arrival thresholds, in seconds (fresh / stale).
PACKETS_FRESH_S = 1.0
PACKETS_STALE_S = 2.0

#: Blender heartbeat age thresholds, in seconds (fresh / stale).
BLENDER_FRESH_S = 2.0
BLENDER_STALE_S = 5.0

assert CAMERA_FRESH_S < CAMERA_STALE_S
assert PACKETS_FRESH_S < PACKETS_STALE_S
assert BLENDER_FRESH_S < BLENDER_STALE_S

#: At-rest displacement ceiling in metres. Defined locally on purpose: the
#: source of truth is ``addon/rigprofile/headbone.py``
#: (``REST_GATE_THRESHOLD``) and importing that package would pull bpy into
#: this pure module.
REST_GATE_THRESHOLD_M = 0.25

_KNOWN_BIND_MODES = ("shape_keys", "point_bones", "none")


def make_light(
    state: str,
    reason: str = "",
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one connection light — the ONLY constructor for a light.

    Honesty invariant: a non-green light with an empty reason is a
    programming error and raises here, loudly, instead of being silently
    "fixed" into something plausible. A green light may carry an empty or
    an informational reason.
    """
    if state not in (GREEN, YELLOW, RED):
        raise ValueError(f"unknown connection state: {state!r}")
    if state != GREEN and not (reason and reason.strip()):
        raise ValueError(f"a {state!r} light must carry a non-empty reason")
    return {"state": state, "reason": reason, "detail": detail if detail is not None else {}}


def _number_or_none(value: Any) -> Optional[float]:
    """Return ``value`` as float, or None when absent; reject non-numbers."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _threshold_light(
    age_s: Optional[float],
    fresh_s: float,
    stale_s: float,
    missing_reason: str,
    aging_template: str,
    stale_template: str,
) -> Dict[str, Any]:
    """Map an age to a light under the shared two-threshold rule.

    Green at or under ``fresh_s`` (an age exactly at FRESH is green), yellow
    up to and including ``stale_s`` (exactly at STALE is yellow), red beyond.
    An absent age is red with ``missing_reason``.
    """
    detail = {"age_s": age_s}
    if age_s is None:
        return make_light(RED, missing_reason, detail)
    if age_s <= fresh_s:
        return make_light(GREEN, detail=detail)
    if age_s <= stale_s:
        return make_light(YELLOW, aging_template.format(age=age_s, fresh=fresh_s), detail)
    return make_light(RED, stale_template.format(age=age_s, stale=stale_s), detail)


def _blender_light(age_s: Optional[float], bind: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map heartbeat age plus the bind report to the Blender light.

    The colour judges the bind IN EFFECT. The refused attempt's number only
    ever appears in reason text, never as a fault signal by itself.
    """
    is_bind_object = isinstance(bind, dict)
    rest_raw = bind.get("rest_displacement_m") if is_bind_object else None
    refused_raw = bind.get("refused_rest_displacement_m") if is_bind_object else None
    rest = _number_or_none(rest_raw)
    refused = _number_or_none(refused_raw)
    mode = bind.get("mode") if is_bind_object else None
    channels = bind.get("channels") if is_bind_object else None
    detail = {
        "age_s": age_s,
        "mode": mode,
        "channels": channels,
        "rest_displacement_m": rest,
        "refused_rest_displacement_m": refused,
    }

    # Red: heartbeat absent or stale beyond its threshold.
    if age_s is None:
        return make_light(RED, "no heartbeat has ever arrived from the Blender addon", detail)
    if age_s > BLENDER_STALE_S:
        return make_light(
            RED, f"heartbeat is {age_s:.2f} s old (stale beyond {BLENDER_STALE_S:.1f} s)", detail
        )

    # Red: the bind report itself is absent, malformed, or unknown.
    if bind is None:
        return make_light(RED, "heartbeat is fresh but the bind report is absent", detail)
    if not is_bind_object:
        return make_light(RED, "bind report is malformed: expected a JSON object", detail)
    if mode not in _KNOWN_BIND_MODES:
        return make_light(RED, f"unknown bind mode: {mode!r}", detail)
    if (rest_raw is not None and rest is None) or (refused_raw is not None and refused is None):
        return make_light(RED, "bind report carries a malformed displacement value", detail)

    # Yellow: heartbeat fresh but degraded.
    if mode == "none":
        return make_light(YELLOW, "Blender is open but nothing is bound (mode 'none')", detail)
    if mode == "point_bones" and rest is not None and rest > REST_GATE_THRESHOLD_M:
        return make_light(
            RED,
            f"active point_bones bind moves the mesh {rest:.2f} m at rest, "
            f"above the {REST_GATE_THRESHOLD_M:.2f} m rest gate",
            detail,
        )
    if mode == "shape_keys" and rest is not None and rest > REST_GATE_THRESHOLD_M:
        reason = (
            f"the reverted bind left {rest:.2f} m of residual displacement behind, "
            f"above the {REST_GATE_THRESHOLD_M:.2f} m rest gate"
        )
        if refused is not None:
            reason += f" (the refused attempt measured {refused:.2f} m)"
        return make_light(YELLOW, reason, detail)
    if not isinstance(channels, int) or isinstance(channels, bool):
        return make_light(RED, "bind report does not say how many channels are bound", detail)
    if channels <= 0:
        return make_light(YELLOW, f"bind '{mode}' is active but drives no channels", detail)

    # Yellow: heartbeat still arriving but no longer fresh.
    if age_s > BLENDER_FRESH_S:
        return make_light(
            YELLOW, f"heartbeat is {age_s:.2f} s old (fresh is <= {BLENDER_FRESH_S:.1f} s)", detail
        )

    # Green: healthy heartbeat, channels flowing, bind in effect within gate.
    reason = ""
    if refused is not None:
        reason = (
            "shape keys only; the bone path was refused because it would have moved the mesh "
            f"{refused:.2f} m at rest (refused_rest_displacement_m)"
        )
    return make_light(GREEN, reason, detail)


def build_connections(
    camera_age_s: Optional[float],
    packets_age_s: Optional[float],
    blender_age_s: Optional[float],
    blender_bind: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the connection lights in the frozen contract's order.

    Pure: every fact arrives as a plain value. The contract's ids, labels
    and order are pinned here; the UI must never depend on ``detail``'s
    inner shape to decide a colour.
    """
    camera = _threshold_light(
        camera_age_s,
        CAMERA_FRESH_S,
        CAMERA_STALE_S,
        missing_reason="no camera frame has ever arrived from the capture loop",
        aging_template="camera frame is {age:.2f} s old (fresh is <= {fresh:.1f} s)",
        stale_template="no camera frame for {age:.2f} s (stale beyond {stale:.1f} s)",
    )
    packets = _threshold_light(
        packets_age_s,
        PACKETS_FRESH_S,
        PACKETS_STALE_S,
        missing_reason="no packet has ever been sent to the UDP socket",
        aging_template="last packet was {age:.2f} s ago (fresh is <= {fresh:.1f} s)",
        stale_template="no packet for {age:.2f} s (stale beyond {stale:.1f} s)",
    )
    blender = _blender_light(blender_age_s, blender_bind)
    return [
        {"id": "camera", "label": "Camera", **camera},
        {"id": "packets", "label": "Packets to Blender", **packets},
        {"id": "blender", "label": "Blender rig", **blender},
    ]

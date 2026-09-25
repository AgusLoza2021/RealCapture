"""Headless 30-minute soak test: real UDP transport + consumer + Rig Connector.

Run with:  blender -b --python tools/blender_soak.py -- <minutes> <port> [expected_floor_ms]

The optional third argument is the expected latency floor in ms for the
positive control: pair it with soak_send.py's --stamp-skew-ms so the gate can
prove the latency measurement actually responded to the injected skew.

Builds the synthetic rig, runs the full wizard (scan + bind), starts the
consumer against the given UDP port, then pumps the consumer tick manually at
~60 Hz (bpy.app.timers do not fire in background mode). Streams must come from
tools/soak_send.py. Writes a JSON report next to the session file and exits
non-zero if quality gates fail.
"""

from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else ["30", "11111"]
SOAK_MINUTES = float(argv[0])
PORT = int(argv[1])
EXPECTED_FLOOR_MS = float(argv[2]) if len(argv) > 2 else None


def main() -> int:
    print("=== RealCapture soak setup ===", flush=True)
    import bpy  # noqa: PLC0415

    from tools import blender_smoke_test as smoke  # noqa: PLC0415

    smoke.build_scene()
    smoke.register_addon()
    from addon.ui import _get_consumer  # noqa: PLC0415

    scene = bpy.context.scene
    settings = scene.realcapture
    settings.controller = bpy.data.objects["RealCapture_Controller"]
    settings.rig_face_mesh = bpy.data.objects["FaceMesh"]
    settings.rig_armature = bpy.data.objects["FaceRig"]
    out_dir = os.path.join(REPO_ROOT, "soak_output")
    os.makedirs(out_dir, exist_ok=True)
    settings.rig_profile_path = os.path.join(out_dir, "soak_rig_profile.json")
    session_path = os.path.join(out_dir, "soak_session.jsonl")
    settings.session_path = session_path
    settings.record_session = True

    result = bpy.ops.realcapture.scan_rig()
    assert result == {"FINISHED"}, "scan_rig failed"
    result = bpy.ops.realcapture.bind_rig()
    assert result == {"FINISHED"}, "bind_rig failed"

    consumer = _get_consumer()
    consumer.start(port=PORT)
    consumer.recorder = None  # recorder started below through settings path
    from addon.session import SessionRecorder  # noqa: PLC0415

    recorder = SessionRecorder(session_path)
    recorder.start()
    consumer.recorder = recorder

    # Manual pump: mark the timer as registered so _tick keeps running.
    consumer._timer_registered = True

    duration = SOAK_MINUTES * 60.0
    started = time.perf_counter()
    tick_durations: list[float] = []
    applied_at_start = consumer.stats.packets_applied
    next_report = 60.0
    ticks = 0

    print(f"=== pumping for {SOAK_MINUTES} minutes on port {PORT} ===", flush=True)
    while True:
        loop_start = time.perf_counter()
        elapsed = loop_start - started
        if elapsed >= duration:
            break
        consumer._tick()
        ticks += 1
        tick_durations.append(time.perf_counter() - loop_start)
        # ~60 Hz pump including overhead
        behind = time.perf_counter() - started - ticks / 60.0
        sleep_for = (1.0 / 60.0) - (time.perf_counter() - loop_start)
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            time.sleep(0.0005)
        if elapsed >= next_report:
            stats = consumer.stats
            print(f"[{int(elapsed // 60):02d}:{int(elapsed % 60):02d}] "
                  f"applied={stats.packets_applied} fps={stats.applied_fps:.1f} "
                  f"transport avg={stats.avg_transport_ms:.1f}ms "
                  f"max={stats.max_transport_ms:.1f}ms "
                  f"invalid={stats.invalid_packets}", flush=True)
            next_report += 60.0

    consumer.stop()
    recorder.stop()
    stats = consumer.stats
    tick_durations.sort()
    p95 = tick_durations[int(len(tick_durations) * 0.95)]
    applied = stats.packets_applied - applied_at_start
    session_lines = sum(1 for _ in open(session_path, encoding="utf-8"))
    controller = bpy.data.objects["RealCapture_Controller"]
    report = {
        "minutes": SOAK_MINUTES,
        "port": PORT,
        "wall_seconds": time.perf_counter() - started,
        "ticks": ticks,
        "packets_applied": applied,
        "applied_fps": stats.applied_fps,
        "transport_avg_ms": stats.avg_transport_ms,
        "transport_max_ms": stats.max_transport_ms,
        "session_max_transport_ms": stats.session_max_transport_ms,
        "invalid_packets": stats.invalid_packets,
        "tick_p95_ms": p95 * 1000.0,
        "session_lines": session_lines,
        "rc_shape_jawOpen": controller.get("rc_shape_jawOpen"),
        "engine": stats.engine,
    }
    if EXPECTED_FLOOR_MS is not None:
        report["expected_latency_floor_ms"] = EXPECTED_FLOOR_MS
    report_path = os.path.join(out_dir, "soak_report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print("=== SOAK REPORT ===", flush=True)
    print(json.dumps(report, indent=2), flush=True)

    from tools.soak_gates import evaluate_soak_gates  # noqa: PLC0415

    failures = evaluate_soak_gates(report)
    if failures:
        for failure in failures:
            print(f"SOAK GATE FAILED: {failure}", flush=True)
        return 1
    print("SOAK GATES PASSED", flush=True)
    return 0


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        traceback.print_exc()
        print("SOAK CRASHED", flush=True)
        code = 2
    sys.exit(code)

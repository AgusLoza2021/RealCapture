"""Contract tests for the C4 installed-extension start-proof harness.

The harness (``tools/blender_start_proof.py``) has two layers:

- a PURE verdict layer (importable without bpy) that decides, from the JSON
  report the runtime layer records, whether the C4 proof actually held: the
  installed extension identity, the backend child, the dashboard lights,
  packet progression, real rig movement, honest coverage truth from raw
  producer channel NAMES, and the
  cleanup truth (PID dead via an independent query, ports released);
- a bpy runtime layer that only ever runs inside Blender.

These tests pin the pure layer. The defect family they exist for: a harness
that reports green on absence, stale data, unknown states, or catalog-size
inference. Every helper here treats absence, staleness and unknown as failure
— the same "absence is never green" rule the cockpit and dashboard already
enforce — so a mutant that flips any check is killed by a named test.
"""

from __future__ import annotations

import ast
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from addon.rigprofile import channels as ch
from tools import blender_start_proof as proof

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "tools" / "blender_start_proof.py"


# -- fixtures ------------------------------------------------------------------


def healthy_cleanup() -> dict:
    return {
        "capture_stopped": True,
        "backend_stop": {"stopped": True, "reason": "backend stopped (exit code 0)"},
        "extension_state_cleared": True,
        "pid_check": {
            "alive": False,
            "method": "tasklist",
            "evidence": "INFO: No tasks are running which match the specified criteria.",
        },
        "ports": {
            "udp": {"released": True, "evidence": "bind 127.0.0.1:11111 succeeded"},
            "dashboard": {"released": True,
                          "evidence": "bind+listen 127.0.0.1:8765 succeeded"},
        },
    }


def healthy_report() -> dict:
    return {
        "schema": proof.REPORT_SCHEMA,
        "extension": {
            "module": proof.RC_EXTENSION_MODULE,
            "dev_module_refused": True,
            "preferences_saved": False,
            "enabled_in_session": True,
        },
        "backend": {
            "started": True,
            "pid": 4242,
            "reason": "backend started (pid 4242); dashboard port 8765 was checked",
            "log_path": "soak_output/backend.log",
        },
        "dashboard": {
            "connections": [
                {"id": "camera", "label": "Camera", "state": "green", "reason": "fresh"},
                {
                    "id": "packets",
                    "label": "Packets to Blender",
                    "state": "green",
                    "reason": "fresh",
                },
                {
                    "id": "blender",
                    "label": "Blender rig",
                    "state": "green",
                    "reason": "bind healthy",
                },
            ],
            "fetched_at": 100.0,
            "now_s": 100.5,
            "error": None,
        },
        "live": {
            "packet_samples": [10, 40, 90],
            "packets_applied": 90,
            "movement": {
                "moved": True,
                "peak_deviations": {"shapekey::jawOpen": 0.5},
                "target_deviations": {"shapekey::jawOpen": 0.5},
            },
            "controller_changed": {"rc_pose_rx": 0.2},  # diagnostics only
        },
        "coverage": proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED),
        # Honest 51/52: 51 ARKit matches + MediaPipe's `_neutral`, tongueOut
        # absent. No synthetic target sweep is claimed by this run; the
        # historical 52/52 sweep is separate task evidence.
        "cleanup": healthy_cleanup(),
    }


# -- healthy pass ----------------------------------------------------------------


def test_a_healthy_report_fails_nothing() -> None:
    assert proof.evaluate_proof(healthy_report()) == []


def test_a_missing_section_is_a_failure_not_a_pass() -> None:
    for section in ("extension", "backend", "dashboard", "live", "coverage", "cleanup"):
        report = healthy_report()
        del report[section]
        failures = proof.evaluate_proof(report)
        assert failures, f"deleting {section!r} still produced a green verdict"


# -- installed module identity -----------------------------------------------------


def test_the_extension_identity_must_be_the_exact_installed_module() -> None:
    for wrong in ("addon", "bl_ext.user_default.real_capture", "realcapture", None):
        report = healthy_report()
        report["extension"]["module"] = wrong
        failures = proof.evaluate_proof(report)
        assert any(proof.RC_EXTENSION_MODULE in f for f in failures), (
            f"identity {wrong!r} was accepted"
        )


def test_dev_package_substitution_must_be_proven_refused() -> None:
    report = healthy_report()
    report["extension"]["dev_module_refused"] = False
    failures = proof.evaluate_proof(report)
    assert any("addon" in f and "refus" in f for f in failures)
    report["extension"].pop("dev_module_refused")
    assert any("refus" in f for f in proof.evaluate_proof(report))


def test_saving_preferences_is_a_failure_even_when_everything_else_holds() -> None:
    report = healthy_report()
    report["extension"]["preferences_saved"] = True
    assert any("preferences" in f for f in proof.evaluate_proof(report))


def test_a_session_without_proven_enable_is_a_failure() -> None:
    report = healthy_report()
    report["extension"]["enabled_in_session"] = None
    assert any("enabled" in f for f in proof.evaluate_proof(report))


# -- backend child -------------------------------------------------------------------


def test_a_missing_or_dead_child_is_a_failure() -> None:
    for backend in (
        {"started": False, "pid": None, "reason": "port held", "log_path": ""},
        {"started": True, "pid": None, "reason": "r", "log_path": "l"},
        {"started": True, "pid": 0, "reason": "r", "log_path": "l"},
        {"started": True, "pid": "4242", "reason": "r", "log_path": "l"},
    ):
        report = healthy_report()
        report["backend"] = backend
        failures = proof.evaluate_proof(report)
        assert failures, f"backend record {backend!r} was accepted"


def test_a_child_without_reason_and_log_is_a_failure() -> None:
    report = healthy_report()
    report["backend"]["reason"] = ""
    report["backend"]["log_path"] = ""
    failures = proof.evaluate_proof(report)
    assert any("reason" in f for f in failures)
    assert any("log" in f for f in failures)


# -- dashboard lights ------------------------------------------------------------------


@pytest.mark.parametrize("light_id", proof.LIGHT_IDS)
def test_each_required_light_must_be_present_and_green(light_id: str) -> None:
    for mutation in ("absent", "red", "yellow", "unknown", "uppercase"):
        report = healthy_report()
        connections = report["dashboard"]["connections"]
        if mutation == "absent":
            report["dashboard"]["connections"] = [
                c for c in connections if c["id"] != light_id
            ]
        elif mutation == "uppercase":
            for c in connections:
                if c["id"] == light_id:
                    c["state"] = "GREEN"  # exact identity: no case-insensitive green
        else:
            for c in connections:
                if c["id"] == light_id:
                    c["state"] = mutation
        failures = proof.evaluate_proof(report)
        assert any(light_id in f for f in failures), (
            f"light {light_id!r} with mutation {mutation!r} was accepted"
        )


def test_a_dashboard_snapshot_that_is_absent_or_stale_is_never_green() -> None:
    for dashboard in (
        {"connections": healthy_report()["dashboard"]["connections"],
         "fetched_at": 0.0, "now_s": 100.0, "error": None},
        {"connections": healthy_report()["dashboard"]["connections"],
         "fetched_at": 100.0, "now_s": 100.0 + proof.MAX_SNAPSHOT_AGE_S + 0.1,
         "error": None},
        {"connections": healthy_report()["dashboard"]["connections"],
         "fetched_at": 100.0, "now_s": 100.0, "error": "connection refused"},
        {"connections": "not a list", "fetched_at": 100.0, "now_s": 100.0,
         "error": None},
    ):
        report = healthy_report()
        report["dashboard"] = dashboard
        failures = proof.evaluate_proof(report)
        assert failures, f"dashboard record {dashboard!r} was accepted"


def test_the_verdict_reads_only_the_final_dashboard_snapshot() -> None:
    # The pre-capture snapshot is diagnostic-only: a green-looking initial
    # snapshot must never rescue a stale or absent final one, because only
    # the final snapshot can show a live Blender heartbeat.
    report = healthy_report()
    report["dashboard_initial"] = report["dashboard"]  # fresh, green
    report["dashboard"] = {**report["dashboard"], "fetched_at": 0.0}  # never fetched
    failures = proof.evaluate_proof(report)
    assert any("stale" in f or "snapshot" in f for f in failures)
    # And an extra diagnostic snapshot cannot break an otherwise healthy run:
    healthy = healthy_report()
    healthy["dashboard_initial"] = {"garbage": True}
    assert proof.evaluate_proof(healthy) == []


def test_run_proof_fetches_the_dashboard_in_the_required_order() -> None:
    # dashboard_initial (diagnostic) < start_capture < pump < FINAL dashboard
    # fetch: the verdict's snapshot must be the post-pump one.
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_proof = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_proof"
    )
    marks: list[tuple[int, str]] = []
    for node in ast.walk(run_proof):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id if isinstance(node.func, ast.Name)
            else getattr(node.func, "attr", "")
        )
        if name in ("poll_dashboard_status", "start_capture_via_operator",
                    "pump_consumer"):
            marks.append((node.lineno, name))
    order = [name for _line, name in marks]
    assert order == [
        "poll_dashboard_status", "start_capture_via_operator",
        "pump_consumer", "poll_dashboard_status",
    ], (
        "run_proof must fetch the initial dashboard, start capture, pump, "
        f"then refetch the final dashboard; got {order}"
    )
    assert "dashboard_initial" in source and '"dashboard"' in source


def test_snapshot_freshness_boundary_is_inclusive() -> None:
    assert proof.snapshot_is_fresh(100.0, 100.0 + proof.MAX_SNAPSHOT_AGE_S)
    assert not proof.snapshot_is_fresh(100.0, 100.0 + proof.MAX_SNAPSHOT_AGE_S + 0.01)
    assert not proof.snapshot_is_fresh(0.0, 100.0)  # never fetched
    assert not proof.snapshot_is_fresh(100.0, 99.0)  # clock going backwards


def test_light_by_id_returns_none_for_absence() -> None:
    lights = [{"id": "camera", "state": "green"}]
    assert proof.light_by_id(lights, "camera") == lights[0]
    assert proof.light_by_id(lights, "packets") is None
    assert proof.light_by_id(None, "camera") is None
    assert proof.light_by_id([{"no": "id"}], "camera") is None


# -- packet progression and rig movement ----------------------------------------------


def test_packets_that_do_not_progress_are_a_failure() -> None:
    for samples in ([10, 10, 10], [90, 40, 10], [10], [], None, [10, "40", 90]):
        report = healthy_report()
        report["live"]["packet_samples"] = samples
        failures = proof.evaluate_proof(report)
        assert any("progress" in f for f in failures), (
            f"packet samples {samples!r} were accepted as progressing"
        )


def test_packet_progression_is_measured_on_the_cumulative_count() -> None:
    assert proof.packets_progressing([10, 11])
    assert proof.packets_progressing([10, 1000])
    assert not proof.packets_progressing([10, 10.5])  # sub-increase is not progress
    assert not proof.packets_progressing([])  # absence is never green


def test_a_rig_that_does_not_move_is_a_failure() -> None:
    report = healthy_report()
    report["live"]["movement"] = {"moved": False, "peak_deviations": {}}
    assert any("move" in f for f in proof.evaluate_proof(report))
    report["live"].pop("movement")
    assert any("move" in f for f in proof.evaluate_proof(report))


def test_target_movement_requires_accumulated_shape_key_deviations() -> None:
    # The actual-rig movement gate: only non-Basis shape-key deviations
    # count. Controller (rc_shape_/rc_pose_) and metadata (rc_meta_) values
    # are diagnostics and can never green the gate by themselves.
    assert proof.target_moved({"shapekey::jawOpen": 0.5})
    assert proof.target_moved({"rc_meta_conf": 0.9, "shapekey::jawOpen": 0.001})
    assert not proof.target_moved({"rc_meta_conf": 0.9})
    assert not proof.target_moved({"rc_meta_engine": 1.0})
    assert not proof.target_moved({"rc_pose_rx": 0.4})
    assert not proof.target_moved({"rc_shape_jawOpen": 0.5})
    assert not proof.target_moved({"shapekey::Basis": 0.9})  # Basis is never a target
    assert not proof.target_moved({})
    assert not proof.target_moved(None)
    assert not proof.target_moved({"shapekey::jawOpen": 1e-9})  # below threshold


def test_metadata_or_controller_only_jitter_cannot_green_the_rig() -> None:
    for peak in (
        {"rc_meta_conf": 0.9, "rc_meta_engine": 1.0},       # metadata jitter
        {"rc_pose_rx": 0.4, "rc_shape_jawOpen": 0.0},       # controller wrote, target did not
        {"shapekey::Basis": 0.9},                            # Basis is never a target
    ):
        report = healthy_report()
        report["live"]["movement"] = {"moved": True, "peak_deviations": peak}
        failures = proof.evaluate_proof(report)
        assert any("shape" in f.lower() or "target" in f.lower() for f in failures), (
            f"peak deviations {peak!r} were accepted as actual rig movement"
        )


def test_the_movement_window_accumulates_shape_key_spikes() -> None:
    baseline = {"shapekey::jawOpen": 0.0}
    samples = [
        {"shapekey::jawOpen": 0.0},
        {"shapekey::jawOpen": 0.6},  # mid-window spike
        {"shapekey::jawOpen": 0.0},  # returned to baseline by the end
    ]
    deviations = proof.movement_from_samples(baseline, samples)
    assert deviations["shapekey::jawOpen"] == pytest.approx(0.6)
    assert proof.window_moved(deviations), (
        "a value that spiked mid-window and returned to baseline must still "
        "prove movement; final-only comparison hides it"
    )
    assert proof.target_moved(deviations), (
        "an accumulated shape-key spike must satisfy the actual-rig gate"
    )


def test_movement_accumulation_ignores_noise_and_counts_new_props() -> None:
    baseline = {"rc_shape_jawOpen": 0.5, "rc_pose_tx": 0.1}
    deviations = proof.movement_from_samples(baseline, [
        {"rc_shape_jawOpen": 0.5 + 1e-9},  # below threshold noise
        {"rc_shape_newChannel": 0.0},       # new prop, but zero is not movement
        {"rc_pose_tx": 0.1},                # unchanged
        {"rc_meta_conf": True},             # bools never count
    ])
    assert not proof.window_moved(deviations)
    assert "rc_meta_conf" not in deviations
    new_baseline = proof.movement_from_samples({}, [{"rc_shape_jawOpen": 0.7}])
    assert proof.window_moved(new_baseline)  # a newly-written nonzero prop moved
    assert proof.movement_from_samples(baseline, None) == {}  # absence never moves


# -- bounded waits ---------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.t

    def step(self, dt: float) -> None:
        self.t += dt


def test_wait_until_returns_exactly_at_the_deadline_boundary() -> None:
    clock = FakeClock()

    def predicate() -> bool:
        return clock.t >= 1.0

    # The sleep MUST advance the injected clock: a no-op sleep would freeze
    # the clock forever (the exact hang this suite once shipped).
    ok, elapsed = proof.wait_until(
        predicate, timeout_s=1.0, interval_s=0.25,
        clock=clock, sleep=clock.step,
    )
    assert ok is True
    assert elapsed == pytest.approx(1.0)
    assert clock.t == 1.0  # it never waited past the deadline


def test_wait_until_reports_failure_at_the_deadline_without_waiting_past_it() -> None:
    clock = FakeClock()
    ok, elapsed = proof.wait_until(
        lambda: False, timeout_s=1.0, interval_s=0.25,
        clock=clock, sleep=lambda _s: clock.step(0.25),
    )
    assert ok is False
    assert elapsed == pytest.approx(1.0)
    assert clock.t == pytest.approx(1.0)


def test_wait_until_predicate_calls_are_bounded() -> None:
    clock = FakeClock()
    proof.wait_until(
        lambda: False, timeout_s=1.0, interval_s=0.25,
        clock=clock, sleep=lambda _s: clock.step(0.25),
    )
    assert clock.calls <= 8  # bounded, not an unbounded spin


def test_wait_until_accepts_an_immediately_true_predicate() -> None:
    # A frozen fake clock at 0.0 makes the elapsed decision deterministic;
    # a real monotonic clock would make elapsed nonzero by microseconds.
    ok, elapsed = proof.wait_until(
        lambda: True, timeout_s=5.0, interval_s=0.1,
        clock=lambda: 0.0, sleep=lambda _s: None,
    )
    assert ok is True
    assert elapsed == 0.0


def test_wait_until_cannot_hang_when_the_injected_clock_never_advances() -> None:
    # Defense in depth for the hang defect class: even a frozen clock and a
    # no-op sleep must terminate through the iteration cap, and a frozen
    # clock must never be mistaken for a satisfied deadline.
    ok, elapsed = proof.wait_until(
        lambda: False, timeout_s=1.0, interval_s=0.25,
        clock=lambda: 0.0, sleep=lambda _s: None,
    )
    assert ok is False
    assert elapsed == 0.0


# -- cleanup truth ---------------------------------------------------------------------


def test_cleanup_that_is_missing_refused_or_unproven_is_a_failure() -> None:
    variants: list[dict] = [
        {},  # whole record absent
        {**healthy_cleanup(), "capture_stopped": False},
        {**healthy_cleanup(), "backend_stop": {"stopped": False, "reason": "still running"}},
        {**healthy_cleanup(), "backend_stop": "not a dict"},
        {**healthy_cleanup(), "extension_state_cleared": False},
        del_key(healthy_cleanup(), "extension_state_cleared"),
        del_key(healthy_cleanup(), "pid_check"),
        {**healthy_cleanup(), "pid_check": {"alive": True, "method": "tasklist", "evidence": "python.exe"}},
        {**healthy_cleanup(), "pid_check": {"alive": None, "method": "tasklist", "evidence": "x"}},
        {**healthy_cleanup(), "pid_check": {"alive": False, "method": "", "evidence": "x"}},
        {**healthy_cleanup(), "pid_check": {"alive": False, "method": "tasklist", "evidence": ""}},
        {**healthy_cleanup(), "ports": {}},
        del_key(healthy_cleanup(), "ports"),
        {**healthy_cleanup(),
         "ports": {"udp": {"released": False, "evidence": "bind refused: held"},
                   "dashboard": {"released": True, "evidence": "refused"}}},
        {**healthy_cleanup(),
         "ports": {"udp": {"released": True, "evidence": "bind ok"},
                   "dashboard": {"released": True, "evidence": ""}}},
        {**healthy_cleanup(),
         "ports": {"udp": {"released": True, "evidence": "bind ok"},
                   "dashboard": {"released": None,
                                 "evidence": "connect timed out; unknown is not release"}}},
    ]
    for cleanup in variants:
        report = healthy_report()
        report["cleanup"] = cleanup
        failures = proof.evaluate_proof(report)
        assert failures, f"cleanup record {cleanup!r} was accepted as complete"


def del_key(mapping: dict, key: str) -> dict:
    cleaned = dict(mapping)
    del cleaned[key]
    return cleaned


def test_pid_alive_names_the_surviving_child() -> None:
    report = healthy_report()
    report["cleanup"]["pid_check"] = {
        "alive": True, "method": "tasklist", "evidence": "python.exe 4242 ...",
    }
    failures = proof.evaluate_proof(report)
    assert any("alive" in f for f in failures)


def test_cleanup_never_stops_the_backend_process_directly() -> None:
    # The stop_backend operator owns the BackendProcess tree kill; a direct
    # process.stop() in cleanup would double-stop the child and desynchronize
    # the extension's own state. ANY ``.stop()`` call in run_cleanup is a
    # defect, regardless of the receiver.
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_cleanup = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_cleanup"
    )
    direct_stops = [
        node for node in ast.walk(run_cleanup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stop"
    ]
    assert not direct_stops, (
        "run_cleanup must stop the backend only through the installed "
        "stop_backend operator, never by calling any process.stop() itself"
    )
    assert "process.stop()" not in source


def test_cleanup_derives_stop_truth_from_the_exact_operator_result() -> None:
    # Operator results are sets; comparing str(set) ("{'FINISHED'}") would be
    # a repr accident, not a result. The exact helper must decide, for BOTH
    # stop operators, and the JSON record is a separate representation.
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_cleanup = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_cleanup"
    )
    body = ast.get_source_segment(source, run_cleanup) or ""
    assert "operator_finished(" in body, (
        "stop truth must be derived from the exact operator result object"
    )
    assert "{'FINISHED'}" not in body, (
        "str(set) comparison must never decide stop truth"
    )
    exact_calls = [
        node for node in ast.walk(run_cleanup)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name)
             and node.func.id == "operator_finished")
            or (isinstance(node.func, ast.Attribute)
                and node.func.attr == "operator_finished")
        )
    ]
    assert len(exact_calls) >= 2, (
        "both stop operators (capture and backend) must be judged by the "
        "exact result helper"
    )


def test_operator_finished_is_an_exact_result_identity() -> None:
    assert proof.operator_finished({"FINISHED"})
    assert proof.operator_finished(frozenset({"FINISHED"}))
    assert not proof.operator_finished("{'FINISHED'}")  # a repr is not a result
    assert not proof.operator_finished({"CANCELLED"})
    assert not proof.operator_finished({"FINISHED", "CANCELLED"})
    assert not proof.operator_finished(set())
    assert not proof.operator_finished(None)


def test_operator_repr_is_json_safe_and_does_not_decide_truth() -> None:
    assert proof.operator_repr({"FINISHED"}) == "FINISHED"
    assert proof.operator_repr(frozenset({"CANCELLED", "FINISHED"})) == (
        "CANCELLED, FINISHED"
    )
    assert proof.operator_repr(None) == "none"
    assert proof.operator_repr("failed: boom") == "failed: boom"


def test_port_release_truth_reports_held_sockets() -> None:
    held_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    held_udp.bind(("127.0.0.1", 0))
    held_udp_port = held_udp.getsockname()[1]
    served = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    served.bind(("127.0.0.1", 0))
    served.listen(1)
    served_port = served.getsockname()[1]
    try:
        truth = proof.port_release_truth(held_udp_port, served_port)
        assert truth["udp"]["released"] is False, "a bound UDP port is not released"
        assert truth["dashboard"]["released"] is False, (
            "a served TCP port cannot be bound+listened on: it is held"
        )
        assert truth["dashboard"]["evidence"]
    finally:
        held_udp.close()
        served.close()


def test_freshly_released_ports_bind_and_prove_release() -> None:
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp_port = udp.getsockname()[1]
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(("127.0.0.1", 0))
    tcp.listen(1)
    tcp_port = tcp.getsockname()[1]
    udp.close()
    tcp.close()
    truth = proof.port_release_truth(udp_port, tcp_port)
    assert truth["udp"]["released"] is True, (
        "a closed UDP port must bind: it is released"
    )
    assert truth["dashboard"]["released"] is True, (
        "a freshly closed TCP port must bind+listen: it is released"
    )


def test_dashboard_release_does_not_depend_on_connect_timeouts() -> None:
    # This host's firewall drops loopback SYNs to closed ports, so a connect
    # to a RELEASED port can time out; connect-based probing is structurally
    # banned. Bind+listen is the release proof.
    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "port_release_truth"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert ".connect(" not in body, (
        "port release must never be probed with connect(); bind+listen only"
    )
    probe = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_dashboard_release_probe"
    )
    probe_body = ast.get_source_segment(source, probe) or ""
    assert ".connect(" not in probe_body
    for fn_node in (probe, fn):
        fn_body = ast.get_source_segment(source, fn_node) or ""
        assert "SO_REUSEADDR" not in fn_body, (
            "SO_REUSEADDR could share the port with a live listener and fake "
            "release"
        )
    assert "SO_EXCLUSIVEADDRUSE" in probe_body, (
        "on Windows the exclusive bind option prevents port sharing"
    )


# -- coverage wording: producer vs synthetic target sweep -------------------------------


def test_inflating_coverage_from_the_catalog_size_is_a_failure() -> None:
    # The C4 false claim: 52 raw names (51 ARKit + _neutral) were reported as
    # live 52/52 by comparing counts. The claim must equal what the recorded
    # NAMES imply; the honest wording for the same names is accepted.
    report = healthy_report()
    report["coverage"]["producer_claim"] = "live 52/52"
    failures = proof.evaluate_proof(report)
    assert any("producer_claim" in f for f in failures), failures
    report["coverage"]["producer_claim"] = "live 51/52"
    assert proof.evaluate_proof(report) == []


def test_never_measured_live_producer_cannot_claim_anything() -> None:
    report = healthy_report()
    report["coverage"] = proof.coverage_truth(ARKIT_CATALOG, None)
    assert report["coverage"]["producer_claim"] is None
    failures = proof.evaluate_proof(report)
    assert any("raw_observed" in f for f in failures)


def test_zero_observed_live_channels_is_never_green() -> None:
    report = healthy_report()
    report["coverage"] = proof.coverage_truth(ARKIT_CATALOG, [])
    failures = proof.evaluate_proof(report)
    assert any("zero" in f.lower() for f in failures), (
        "a run that observed no live ARKit shape channels must never pass"
    )


def test_observed_channels_must_be_data_this_consumer_run_wrote() -> None:
    # Live channel coverage comes from the exact rc_shape_ keys in the
    # consumer's _last_values (cleared at _begin, filled only by packets this
    # run applied). Pre-existing controller props, pose keys, and metadata
    # never count as ARKit shape channels.
    keys = {
        "rc_shape_jawOpen", "rc_shape_eyeBlinkLeft",
        "rc_pose_rx", "rc_meta_conf", "rc_meta_engine",
        "rc_pose_staleFromEarlierSession", "unrelated", 42, None,
    }
    assert proof.live_shape_channel_names(keys) == ["eyeBlinkLeft", "jawOpen"]
    assert proof.live_shape_channel_names(set()) == []
    assert proof.live_shape_channel_names({"rc_shape_jawOpen"}) == ["jawOpen"]
    assert proof.live_shape_channel_names({"rc_shape_"}) == []  # bare prefix
    assert proof.live_shape_channel_names(None) == []
    assert proof.live_shape_channel_names("rc_shape_jawOpen") == []  # not a key set


def test_the_absence_of_a_sweep_claim_does_not_fail_c4() -> None:
    # This run executes no synthetic target sweep; the historical 52/52 sweep
    # is separate task evidence OUTSIDE this report. Absence of a sweep claim
    # must not fail the verdict: the sweep is simply not part of this run's
    # contract.
    report = healthy_report()
    assert not [f for f in proof.evaluate_proof(report) if "sweep" in f.lower()]


def test_an_observed_catalog_count_above_the_catalog_is_a_failure() -> None:
    # Only len(configured) names can ever match the catalog; a forged higher
    # count is an impossible partition and must fail the full verdict.
    report = healthy_report()
    report["coverage"]["observed_catalog_channels"] = 53
    assert proof.evaluate_proof(report)


# -- regression: the C4 coverage false claim (live 52/52 from 52 raw names) -------------
#
# Immutable live evidence (proof.json, %TEMP%/rc-start-proof-20260927-154632/):
# the producer emitted 52 raw channel names = 51 of the 52 ARKit names
# (tongueOut absent) plus MediaPipe's extra `_neutral`. The old helper compared
# len(raw) with len(configured) and reported a false `live 52/52`. The new
# coverage truth computes the intersection/difference from the NAMES themselves.

ARKIT_CATALOG = list(ch.ARKIT_CHANNELS)
RAW_OBSERVED = sorted((set(ARKIT_CATALOG) - {"tongueOut"}) | {"_neutral"})


def test_report_schema_is_bumped_to_v2_for_the_new_coverage_semantics() -> None:
    assert proof.REPORT_SCHEMA == "realcapture-blender-start-proof/2"


def test_honest_51_of_52_producer_coverage_passes_the_full_proof() -> None:
    report = healthy_report()
    report["coverage"] = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    coverage = report["coverage"]
    assert coverage["configured_channels"] == 52
    assert coverage["raw_observed_channels"] == 52
    assert coverage["raw_observed_channel_names"] == RAW_OBSERVED
    assert coverage["observed_catalog_channels"] == 51
    assert coverage["unexpected_channel_names"] == ["_neutral"]
    assert coverage["missing_configured_channel_names"] == ["tongueOut"]
    assert coverage["producer_claim"] == "live 51/52"
    assert proof.evaluate_proof(report) == [], proof.evaluate_proof(report)


def test_raw_count_equal_to_catalog_count_is_never_coverage() -> None:
    # 52 raw names (51 catalog matches + _neutral) must never read as live
    # 52/52: coverage is the name intersection, never len(raw) vs len(configured).
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    assert truth["producer_claim"] != "live 52/52"
    assert truth["observed_catalog_channels"] == 51


def test_zero_catalog_matches_fail_closed() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, ["_neutral", "unknownFace"])
    failures = proof.coverage_failures(truth)
    assert any("zero" in f.lower() for f in failures), failures


def test_zero_observed_raw_names_fail_closed() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, [])
    failures = proof.coverage_failures(truth)
    assert any("zero" in f.lower() for f in failures), failures


def test_inflated_producer_claim_fails() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    truth["producer_claim"] = "live 52/52"
    failures = proof.coverage_failures(truth)
    assert failures, "an inflated producer claim was accepted"


def test_impossible_partition_fails() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    truth["observed_catalog_channels"] = 52  # only 51 names can match
    assert proof.coverage_failures(truth)
    truth["missing_configured_channel_names"] = []  # tongueOut cannot return
    assert proof.coverage_failures(truth)


def test_duplicate_or_non_name_entries_fail() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    truth["raw_observed_channel_names"] = RAW_OBSERVED + ["jawOpen"]
    assert any("duplicate" in f for f in proof.coverage_failures(truth))
    truth["raw_observed_channel_names"] = ["jawOpen", 42]
    assert any("non-name" in f or "malformed" in f or "not a name" in f
               for f in proof.coverage_failures(truth))


def test_malformed_counts_fail() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    for field in ("configured_channels", "raw_observed_channels",
                  "observed_catalog_channels"):
        broken = dict(truth)
        broken[field] = None
        assert any(field in f for f in proof.coverage_failures(broken)), field
        broken = dict(truth)
        broken[field] = True  # a bool is never a count
        assert any(field in f for f in proof.coverage_failures(broken)), field


def test_unmeasured_catalog_or_names_cannot_claim_coverage() -> None:
    # An unimportable catalog and an unmeasured live run must both fail the
    # verdict instead of silently claiming anything.
    unmeasured = proof.coverage_truth(ARKIT_CATALOG, None)
    assert unmeasured["producer_claim"] is None
    assert proof.coverage_failures(unmeasured)
    no_catalog = proof.coverage_truth(None, RAW_OBSERVED)
    assert no_catalog["producer_claim"] is None
    assert proof.coverage_failures(no_catalog)


def test_the_live_report_carries_raw_names_and_run_proof_feeds_the_catalog() -> None:
    # Semantics guard: the live block records RAW producer names (never
    # `observed_live_*`, which conflated raw with catalog coverage), and
    # run_proof passes the exact installed ARKIT_CHANNELS plus those raw
    # names into coverage_truth.
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert '"raw_observed_channel_names"' in source
    assert '"raw_observed_channels"' in source
    assert '"observed_live_channels"' not in source
    assert '"observed_live_channel_names"' not in source
    tree = ast.parse(source)
    run_proof = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_proof"
    )
    body = ast.get_source_segment(source, run_proof) or ""
    assert "coverage_truth(" in body
    assert "ARKIT_CHANNELS" in body
    assert "raw_observed_channel_names" in body


# -- regression: truncated catalogs and degraded producers must fail C4 -----------------
#
# C4 is specifically the installed default MediaPipe + ARKit-52 proof. The
# catalog-size check above catches a missing count, but a TRUNCATED installed
# catalog (e.g. one channel) would previously pass as `live 1/1`, and a
# producer degraded to 1 catalog match would pass merely by being nonzero.


def test_named_constants_pin_the_catalog_and_minimum() -> None:
    assert proof.EXPECTED_CONFIGURED_CHANNELS == 52
    assert proof.MINIMUM_LIVE_CATALOG_MATCHES == 51


def test_a_truncated_configured_catalog_fails_even_when_fully_observed() -> None:
    # Three unique configured names (tongueOut included, no _neutral), all
    # observed: internally consistent, yet not the ARKit-52 proof.
    truncated = ["jawOpen", "mouthPucker", "tongueOut"]
    truth = proof.coverage_truth(truncated, truncated)
    assert truth["producer_claim"] == "live 3/3"  # consistent, but not C4
    failures = proof.coverage_failures(truth)
    assert any("52" in f for f in failures), failures
    report = healthy_report()
    report["coverage"] = truth
    assert proof.evaluate_proof(report), "a truncated catalog passed the verdict"


def test_a_grown_configured_catalog_fails_even_when_fully_observed() -> None:
    grown = ARKIT_CATALOG + ["futureChannel"]
    truth = proof.coverage_truth(grown, grown)
    failures = proof.coverage_failures(truth)
    assert any("52" in f for f in failures), failures
    report = healthy_report()
    report["coverage"] = truth
    assert proof.evaluate_proof(report)


def test_a_producer_degraded_below_51_catalog_matches_fails() -> None:
    degraded_raw = sorted(set(ARKIT_CATALOG) - {"tongueOut"})[:40] + ["_neutral"]
    truth = proof.coverage_truth(ARKIT_CATALOG, degraded_raw)
    assert truth["observed_catalog_channels"] == 40  # nonzero, still not enough
    failures = proof.coverage_failures(truth)
    assert any("51" in f for f in failures), failures
    report = healthy_report()
    report["coverage"] = truth
    assert proof.evaluate_proof(report), "a degraded producer passed the verdict"


def test_the_known_media_pipe_contract_51_of_52_passes() -> None:
    # The exact live evidence: 51 ARKit matches + _neutral, tongueOut absent.
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    assert proof.coverage_failures(truth) == []


def test_full_52_of_52_would_pass_if_future_media_pipe_emits_tongue_out() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, ARKIT_CATALOG)
    assert truth["producer_claim"] == "live 52/52"
    assert truth["unexpected_channel_names"] == []
    assert proof.coverage_failures(truth) == []


# -- regression: the configured catalog must carry the ARKit sentinels ------------------
#
# A count of exactly 52 is necessary but not sufficient: a catalog that lost
# `tongueOut` (e.g. patched to match a degraded producer) or absorbed the
# producer-only `_neutral` into configuration would still count 52 and pass.


def test_catalog_sentinel_constants_are_named() -> None:
    assert proof.REQUIRED_CATALOG_SENTINEL == "tongueOut"
    assert proof.FORBIDDEN_CATALOG_SENTINEL == "_neutral"


def test_the_real_catalog_fixture_carries_the_sentinels() -> None:
    assert "tongueOut" in ARKIT_CATALOG
    assert "_neutral" not in ARKIT_CATALOG


def test_a_52_name_catalog_missing_tongue_out_fails_even_when_consistent() -> None:
    # 52 unique configured names, tongueOut absent, _neutral absent, 51 of
    # them observed: internally consistent, still not the ARKit-52 catalog.
    configured = sorted((set(ARKIT_CATALOG) - {"tongueOut"}) | {"fakeBlink"})
    assert len(configured) == 52 and "tongueOut" not in configured
    truth = proof.coverage_truth(configured, sorted(set(configured) - {"fakeBlink"}))
    assert truth["producer_claim"] == "live 51/52"  # consistent, still wrong
    failures = proof.coverage_failures(truth)
    assert any("tongueOut" in f for f in failures), failures
    report = healthy_report()
    report["coverage"] = truth
    assert proof.evaluate_proof(report), "a tongueOut-less catalog passed"


def test_a_52_name_catalog_containing_neutral_fails_even_when_consistent() -> None:
    # 52 unique configured names including producer-only _neutral, all
    # observed: internally consistent, but configuration absorbed a producer
    # artifact instead of the ARKit vocabulary.
    configured = sorted((set(ARKIT_CATALOG) - {"mouthPucker"}) | {"_neutral"})
    assert len(configured) == 52 and "_neutral" in configured
    truth = proof.coverage_truth(configured, configured)
    assert truth["producer_claim"] == "live 52/52"  # consistent, still wrong
    failures = proof.coverage_failures(truth)
    assert any("_neutral" in f for f in failures), failures
    report = healthy_report()
    report["coverage"] = truth
    assert proof.evaluate_proof(report), "a _neutral-polluted catalog passed"


def test_the_healthy_real_catalog_still_passes_at_honest_51_52() -> None:
    truth = proof.coverage_truth(ARKIT_CATALOG, RAW_OBSERVED)
    assert proof.coverage_failures(truth) == []


# -- regression: exact catalog identity via a deterministic digest ----------------------
#
# Count + sentinels still allow a same-size catalog that swaps a non-sentinel
# ARKit name for a fake one. F1-F3 close that: the configured names must hash
# to the exact installed ARKit-52 vocabulary.


def test_the_actual_arkit_catalog_digest_equals_the_named_constant() -> None:
    assert proof.catalog_digest(ARKIT_CATALOG) == (
        proof.EXPECTED_ARKIT_CATALOG_SHA256)


def test_the_digest_is_deterministic_order_insensitive_and_discriminating() -> None:
    digest = proof.catalog_digest(ARKIT_CATALOG)
    assert digest == proof.catalog_digest(list(reversed(ARKIT_CATALOG)))
    assert digest != proof.catalog_digest(ARKIT_CATALOG[:-1] + ["fakeBlink"])
    assert proof.catalog_digest(None) is None  # malformed input, never a digest


def test_a_non_sentinel_name_swap_fails_by_exact_catalog_identity() -> None:
    # 52 unique names, tongueOut present, no _neutral, all 52 observed:
    # every previous check passes, yet the catalog is not ARKit-52.
    swapped = sorted(set(ARKIT_CATALOG) - {"jawOpen"} | {"jawOpenFake"})
    assert len(swapped) == 52 and "tongueOut" in swapped
    assert "_neutral" not in swapped
    truth = proof.coverage_truth(swapped, swapped)
    assert truth["producer_claim"] == "live 52/52"  # consistent, still wrong
    failures = proof.coverage_failures(truth)
    assert any("digest" in f for f in failures), failures
    report = healthy_report()
    report["coverage"] = truth
    assert proof.evaluate_proof(report), "a swapped-name catalog passed"


def test_count_and_sentinel_diagnostics_still_fire_alongside_the_digest() -> None:
    # The digest is the identity check; the readable diagnostics remain.
    polluted = sorted((set(ARKIT_CATALOG) - {"jawOpen"}) | {"_neutral"})
    truth = proof.coverage_truth(polluted, polluted)
    failures = proof.coverage_failures(truth)
    assert any("digest" in f for f in failures)
    assert any("_neutral" in f for f in failures)
    assert any("52" in f for f in failures)


# -- module hygiene: bpy stays lazy -----------------------------------------------------


def test_the_module_imports_without_bpy_regardless_of_ambient_modules() -> None:
    # A fresh subprocess proves laziness structurally: ambient sys.modules in
    # the pytest process (a sibling test may have imported bpy) can never
    # contaminate this check.
    code = (
        "import sys; sys.path.insert(0, r" + repr(str(REPO_ROOT)) + "); "
        "from tools import blender_start_proof as p; "
        "assert p.RC_EXTENSION_MODULE == 'bl_ext.user_default.realcapture'; "
        "assert 'bpy' not in sys.modules, 'bpy was imported by the harness module'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def test_no_top_level_bpy_import_exists_in_the_source() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def mentions_bpy(node: ast.stmt) -> bool:
        if isinstance(node, ast.Import):
            return any(alias.name == "bpy" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            return node.module == "bpy"
        return False

    top_level: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            top_level.append(node)
        elif isinstance(node, ast.Try):
            top_level.extend(n for n in node.body + node.orelse + node.finalbody
                             if isinstance(n, (ast.Import, ast.ImportFrom)))
    offenders = [n for n in top_level if mentions_bpy(n)]
    assert not offenders, (
        f"bpy must be imported lazily inside functions, not at lines "
        f"{[n.lineno for n in offenders]}"
    )


# -- the pure self-test runs under a plain Python ---------------------------------------


def test_write_report_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "proof.json"
    written = proof.write_report({"schema": proof.REPORT_SCHEMA}, str(target))
    assert written == str(target)
    assert target.is_file()  # rereadable


def test_self_test_mode_passes_without_blender() -> None:
    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--self-test"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

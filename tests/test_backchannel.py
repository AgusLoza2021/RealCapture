"""Unit tests for the addon heartbeat back-channel (no bpy, fake sockets)."""

import json
import logging

import pytest

from addon.backchannel import (
    HEARTBEAT_DISCRIMINATOR,
    MAX_HEARTBEAT_BYTES,
    MIN_SEND_INTERVAL_S,
    HeartbeatSender,
    build_heartbeat,
    summarize_bind,
)


class FakeSocket:
    """Records sendto calls, or raises on demand."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[bytes, tuple]] = []
        self.fail = fail

    def sendto(self, data: bytes, addr) -> None:
        if self.fail:
            raise OSError("simulated send failure")
        self.sent.append((data, addr))


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


BIND = {
    "mode": "shape_keys",
    "channels": 12,
    "head_bone": None,
    "rest_displacement_m": 0.0002,          # residual of the bind in effect
    "refused_rest_displacement_m": 0.8319,  # the refused point/bone attempt
    "skip_reason": "rest_gate",
}

ADDR = ("127.0.0.1", 50000)


# -- datagram shape -----------------------------------------------------------


def test_datagram_has_frozen_shape():
    encoded = build_heartbeat(BIND, t_send_ms=1700000000000, revision=3)
    assert isinstance(encoded, bytes)
    assert b"\n" not in encoded  # one JSON datagram, one line
    payload = json.loads(encoded.decode("utf-8"))
    assert set(payload) == {"rc_heartbeat", "t_send_ms", "revision", "bind"}
    assert payload["rc_heartbeat"] == 1
    assert payload["t_send_ms"] == 1700000000000
    assert payload["revision"] == 3
    assert payload["bind"] == BIND


def test_discriminator_is_present():
    payload = json.loads(build_heartbeat(None, 1, 0).decode("utf-8"))
    assert payload[HEARTBEAT_DISCRIMINATOR] == 1


def test_bind_can_be_null():
    payload = json.loads(build_heartbeat(None, 1, 0).decode("utf-8"))
    assert payload["bind"] is None


# -- the 1200-byte bound and the drop-detail behaviour ------------------------


def test_normal_bind_stays_under_the_bound():
    encoded = build_heartbeat(BIND, t_send_ms=1, revision=0)
    assert len(encoded) <= MAX_HEARTBEAT_BYTES


def test_oversized_bind_drops_detail_but_keeps_mode_and_channels():
    # A pathological head bone name must not break the size bound.
    bloated = dict(BIND, head_bone="x" * 5000, rest_displacement_m=0.123456)
    encoded = build_heartbeat(bloated, t_send_ms=1, revision=0)
    assert len(encoded) <= MAX_HEARTBEAT_BYTES
    payload = json.loads(encoded.decode("utf-8"))
    # Detail dropped, identity kept: mode and channels survive.
    assert payload["bind"] == {"mode": "shape_keys", "channels": 12}
    assert payload["rc_heartbeat"] == 1


def test_unsalvageable_bind_dropped_entirely_message_never_split():
    # Even the slim bind (mode + channels) does not fit: drop the whole
    # bind rather than split the message; the discriminator stays.
    bloated = {"mode": "y" * 5000, "channels": 1}
    encoded = build_heartbeat(bloated, t_send_ms=1, revision=0)
    assert len(encoded) <= MAX_HEARTBEAT_BYTES
    payload = json.loads(encoded.decode("utf-8"))
    assert payload["bind"] is None
    assert payload["rc_heartbeat"] == 1


# -- bind summary (pure assembly of values the bind layer already knows) ------


def test_summarize_bind_point_bones_mode():
    # Active bone path: the attempt measurement IS the bind in effect and
    # nothing was refused.
    summary = summarize_bind(
        bone_path_active=True, has_shape_entries=True,
        head_bone="head", attempt_rest_displacement_m=0.0042,
        residual_rest_displacement_m=None, skip_reason=None, channels=17,
    )
    assert summary == {
        "mode": "point_bones",
        "channels": 17,
        "head_bone": "head",
        "rest_displacement_m": 0.0042,
        "refused_rest_displacement_m": None,
        "skip_reason": None,
    }


def test_rest_gate_refusal_reports_residual_never_the_refused_attempt():
    """The conflation defect this test pins: the refused attempt's number
    (the damage measured BEFORE the gate tore the bind down) must never be
    reported as the health of the bind in effect -- that paints a working
    rig as degraded forever. The revert residual is the honest number."""
    summary = summarize_bind(
        bone_path_active=False, has_shape_entries=True,
        head_bone="head", attempt_rest_displacement_m=0.8319,
        residual_rest_displacement_m=0.0002, skip_reason="rest_gate", channels=52,
    )
    assert summary["mode"] == "shape_keys"
    assert summary["rest_displacement_m"] == 0.0002
    assert summary["refused_rest_displacement_m"] == 0.8319
    assert summary["skip_reason"] == "rest_gate"
    # The two numbers must never be the same value: if the refused attempt
    # ever lands in rest_displacement_m, this fails.
    assert summary["rest_displacement_m"] != summary["refused_rest_displacement_m"]


def test_refusal_with_unmeasured_residual_reports_null_not_the_attempt():
    # A revert whose residual was never measured reports null -- never the
    # refused attempt's number as a fallback.
    summary = summarize_bind(
        bone_path_active=False, has_shape_entries=True,
        head_bone="head", attempt_rest_displacement_m=0.8319,
        residual_rest_displacement_m=None, skip_reason="rest_gate", channels=52,
    )
    assert summary["rest_displacement_m"] is None
    assert summary["refused_rest_displacement_m"] == 0.8319


def test_no_head_bone_refusal_has_null_displacements():
    # The attempt was never measured, so there is nothing to refuse.
    summary = summarize_bind(
        bone_path_active=False, has_shape_entries=True,
        head_bone=None, attempt_rest_displacement_m=None,
        residual_rest_displacement_m=None, skip_reason="no_head_bone", channels=52,
    )
    assert summary["rest_displacement_m"] is None
    assert summary["refused_rest_displacement_m"] is None
    assert summary["skip_reason"] == "no_head_bone"


def test_summarize_bind_shape_keys_only_has_null_head_bone():
    # Shape keys bound with no bone path involved at all (profile had no
    # points/bone bindings): skip_reason None, displacements null.
    summary = summarize_bind(
        bone_path_active=False, has_shape_entries=True,
        head_bone="rejected_head", attempt_rest_displacement_m=None,
        residual_rest_displacement_m=None, skip_reason=None, channels=12,
    )
    assert summary["mode"] == "shape_keys"
    # A bone path that is NOT driving the rig must not be reported as one.
    assert summary["head_bone"] is None
    assert summary["rest_displacement_m"] is None
    assert summary["refused_rest_displacement_m"] is None
    assert summary["skip_reason"] is None


def test_summarize_bind_none_mode():
    summary = summarize_bind(
        bone_path_active=False, has_shape_entries=False,
        head_bone=None, attempt_rest_displacement_m=None,
        residual_rest_displacement_m=None, skip_reason=None, channels=0,
    )
    assert summary["mode"] == "none"
    assert summary["channels"] == 0
    assert summary["rest_displacement_m"] is None
    assert summary["refused_rest_displacement_m"] is None


# -- cadence cap ---------------------------------------------------------------


def test_cadence_cap_skips_early_second_send():
    sock = FakeSocket()
    clock = FakeClock()
    sender = HeartbeatSender(clock=clock)
    assert sender.maybe_send(sock, ADDR, BIND) is True
    clock.advance(MIN_SEND_INTERVAL_S / 2)
    assert sender.maybe_send(sock, ADDR, BIND) is False
    assert len(sock.sent) == 1


def test_cadence_cap_allows_send_after_interval():
    sock = FakeSocket()
    clock = FakeClock()
    sender = HeartbeatSender(clock=clock)
    assert sender.maybe_send(sock, ADDR, BIND) is True
    clock.advance(MIN_SEND_INTERVAL_S)
    assert sender.maybe_send(sock, ADDR, BIND) is True
    assert len(sock.sent) == 2


def test_no_reply_target_before_first_packet():
    sock = FakeSocket()
    sender = HeartbeatSender(clock=FakeClock())
    # Nothing has arrived yet: recvfrom gave us no address to answer.
    assert sender.maybe_send(sock, None, BIND) is False
    assert sock.sent == []


def test_revision_flows_into_the_datagram_and_bumps():
    sock = FakeSocket()
    sender = HeartbeatSender(revision=7, clock=FakeClock())
    sender.bump_revision()
    sender.maybe_send(sock, ADDR, BIND)
    payload = json.loads(sock.sent[0][0].decode("utf-8"))
    assert payload["revision"] == 8


# -- send failure swallowed and counted ----------------------------------------


def test_send_failure_swallowed_and_counted():
    sock = FakeSocket(fail=True)
    clock = FakeClock()
    sender = HeartbeatSender(clock=clock)
    assert sender.maybe_send(sock, ADDR, BIND) is False  # never raises
    assert sender.send_failures == 1
    clock.advance(MIN_SEND_INTERVAL_S)
    assert sender.maybe_send(sock, ADDR, BIND) is False
    assert sender.send_failures == 2


def test_failure_logged_once_per_streak(caplog):
    sock = FakeSocket(fail=True)
    clock = FakeClock()
    sender = HeartbeatSender(clock=clock)
    with caplog.at_level(logging.WARNING, logger="addon.backchannel"):
        clock.advance(MIN_SEND_INTERVAL_S)
        sender.maybe_send(sock, ADDR, BIND)
        clock.advance(MIN_SEND_INTERVAL_S)
        sender.maybe_send(sock, ADDR, BIND)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1  # logged once, not once per failure


def test_failure_streak_logged_again_only_after_recovery(caplog):
    good = FakeSocket()
    bad = FakeSocket(fail=True)
    clock = FakeClock()
    sender = HeartbeatSender(clock=clock)
    with caplog.at_level(logging.WARNING, logger="addon.backchannel"):
        sender.maybe_send(bad, ADDR, BIND)  # streak 1: logged
        clock.advance(MIN_SEND_INTERVAL_S)
        sender.maybe_send(good, ADDR, BIND)  # recovery
        clock.advance(MIN_SEND_INTERVAL_S)
        sender.maybe_send(bad, ADDR, BIND)  # streak 2: logged again
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_failed_attempt_counts_against_cadence():
    # A dead link retries at ~2 Hz, not once per 60 Hz tick.
    sock = FakeSocket(fail=True)
    clock = FakeClock()
    sender = HeartbeatSender(clock=clock)
    sender.maybe_send(sock, ADDR, BIND)
    clock.advance(MIN_SEND_INTERVAL_S / 2)
    assert sender.maybe_send(sock, ADDR, BIND) is False
    clock.advance(MIN_SEND_INTERVAL_S / 2)
    assert sender.maybe_send(sock, ADDR, BIND) is False
    assert sender.send_failures == 2

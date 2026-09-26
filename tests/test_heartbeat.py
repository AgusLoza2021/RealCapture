"""Unit tests for the backend heartbeat tracker and read path (fake sockets, no bpy)."""

import json
import socket
import time

import pytest

from backend.backends.base import CaptureBackend
from backend.common.packets import Packet, encode_packet
from backend.dashboard.heartbeat import (
    HeartbeatReader,
    HeartbeatTracker,
    HeartbeatValidationError,
    parse_heartbeat,
)

VALID_POSE = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}

BIND = {
    "mode": "point_bones",
    "channels": 17,
    "head_bone": "head",
    "rest_displacement_m": 0.0042,
    "refused_rest_displacement_m": None,
    "skip_reason": None,
}


def heartbeat_bytes(bind=BIND, revision=3, t_send_ms=1000) -> bytes:
    return json.dumps(
        {"rc_heartbeat": 1, "t_send_ms": t_send_ms, "revision": revision, "bind": bind},
        separators=(",", ":"),
    ).encode("utf-8")


class FakeSocket:
    """Replays canned recvfrom results, then reports the queue as empty."""

    def __init__(self, datagrams: list[bytes]) -> None:
        self.datagrams = list(datagrams)

    def recvfrom(self, bufsize: int):
        if not self.datagrams:
            raise BlockingIOError()
        return self.datagrams.pop(0), ("127.0.0.1", 11111)


class BrokenSocket:
    def recvfrom(self, bufsize: int):
        raise OSError("socket is gone")


# -- tracker: never arrived -----------------------------------------------------


def test_never_arrived_means_age_none():
    tracker = HeartbeatTracker()
    assert tracker.age_s(now=12345.0) is None


def test_never_arrived_bind_report_is_none():
    tracker = HeartbeatTracker()
    assert tracker.bind_report() is None


def test_never_arrived_revision_is_none():
    tracker = HeartbeatTracker()
    assert tracker.revision is None


# -- tracker: arrival sets age and passes the bind through ----------------------


def test_arrival_sets_age():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes()), arrival_s=100.0)
    assert tracker.age_s(now=101.5) == pytest.approx(1.5)
    assert tracker.age_s(now=103.0) == pytest.approx(3.0)


def test_age_uses_current_time_when_now_omitted():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes()), arrival_s=time.monotonic())
    age = tracker.age_s()
    assert age is not None and 0.0 <= age < 5.0


def test_bind_report_passes_through_unchanged():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes(BIND)), arrival_s=1.0)
    assert tracker.bind_report() == BIND


def test_bind_report_passes_null_through():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes(bind=None)), arrival_s=1.0)
    assert tracker.bind_report() is None


def test_bind_report_returns_a_copy():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes(BIND)), arrival_s=1.0)
    report = tracker.bind_report()
    report["channels"] = 999
    assert tracker.bind_report()["channels"] == 17


def test_revision_counter_tracks_latest_datagram():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes(revision=3)), arrival_s=1.0)
    tracker.record(parse_heartbeat(heartbeat_bytes(revision=4)), arrival_s=2.0)
    assert tracker.revision == 4
    assert tracker.age_s(now=2.5) == pytest.approx(0.5)  # last arrival wins


# -- tracker: rejections are counted --------------------------------------------


def test_missing_discriminator_rejected_and_counted():
    tracker = HeartbeatTracker()
    raw = json.dumps({"t_send_ms": 1, "revision": 1, "bind": None}).encode()
    assert tracker.observe(raw, arrival_s=1.0) is False
    assert tracker.invalid_count == 1
    assert tracker.age_s(now=2.0) is None  # nothing was recorded


def test_discriminator_wrong_value_rejected_and_counted():
    tracker = HeartbeatTracker()
    raw = json.dumps({"rc_heartbeat": 2, "t_send_ms": 1, "revision": 1, "bind": None}).encode()
    assert tracker.observe(raw, arrival_s=1.0) is False
    assert tracker.invalid_count == 1


def test_discriminator_wrong_type_rejected_and_counted():
    tracker = HeartbeatTracker()
    raw = json.dumps({"rc_heartbeat": "1", "t_send_ms": 1, "revision": 1, "bind": None}).encode()
    assert tracker.observe(raw) is False
    assert tracker.invalid_count == 1


def test_boolean_discriminator_rejected_and_counted():
    tracker = HeartbeatTracker()
    raw = json.dumps({"rc_heartbeat": True, "t_send_ms": 1, "revision": 1, "bind": None}).encode()
    assert tracker.observe(raw) is False
    assert tracker.invalid_count == 1


def test_garbage_bytes_rejected_and_counted():
    tracker = HeartbeatTracker()
    assert tracker.observe(b"{not json") is False
    assert tracker.observe(b"") is False
    assert tracker.invalid_count == 2


def test_wrong_type_in_top_level_int_fields_rejected():
    tracker = HeartbeatTracker()
    raw = json.dumps({"rc_heartbeat": 1, "t_send_ms": "now", "revision": 1, "bind": None}).encode()
    assert tracker.observe(raw) is False
    assert tracker.invalid_count == 1


def test_wrong_type_in_bind_fields_rejected():
    bad_binds = [
        dict(BIND, mode="skeleton"),            # not a known mode
        dict(BIND, channels=17.5),              # float, not int
        dict(BIND, head_bone=17),               # int, not str/null
        dict(BIND, rest_displacement_m="tiny"), # str, not number/null
        dict(BIND, refused_rest_displacement_m="big"),  # str, not number/null
        dict(BIND, skip_reason="exploded"),     # not a known skip reason
        dict(BIND, skip_reason=3),              # int, not str/null
    ]
    tracker = HeartbeatTracker()
    for bind in bad_binds:
        assert tracker.observe(heartbeat_bytes(bind=bind)) is False
    assert tracker.invalid_count == len(bad_binds)


def test_rejection_does_not_overwrite_the_last_good_state():
    tracker = HeartbeatTracker()
    tracker.record(parse_heartbeat(heartbeat_bytes(revision=9)), arrival_s=1.0)
    tracker.observe(b"garbage")
    assert tracker.revision == 9
    assert tracker.invalid_count == 1


# -- parse_heartbeat: accepted shapes -------------------------------------------


def test_parse_accepts_null_bind():
    payload = parse_heartbeat(heartbeat_bytes(bind=None))
    assert payload["bind"] is None
    assert payload["rc_heartbeat"] == 1


def test_parse_rejects_non_object_json():
    with pytest.raises(HeartbeatValidationError):
        parse_heartbeat(b"[1, 2, 3]")


def test_parse_rejects_unknown_top_level_fields():
    raw = json.dumps(
        {"rc_heartbeat": 1, "t_send_ms": 1, "revision": 1, "bind": None, "extra": 1}
    ).encode()
    with pytest.raises(HeartbeatValidationError):
        parse_heartbeat(raw)


def test_parse_allows_null_optional_bind_fields():
    bind = {
        "mode": "none", "channels": 0, "head_bone": None,
        "rest_displacement_m": None, "refused_rest_displacement_m": None,
        "skip_reason": None,
    }
    payload = parse_heartbeat(heartbeat_bytes(bind=bind))
    assert payload["bind"] == bind


def test_parse_accepts_the_full_rest_gate_bind():
    """The amended contract's reference shape: a refused attempt travels in
    its own field, separate from the residual of the bind in effect."""
    bind = {
        "mode": "shape_keys", "channels": 52, "head_bone": None,
        "rest_displacement_m": 0.0002, "refused_rest_displacement_m": 0.8319,
        "skip_reason": "rest_gate",
    }
    payload = parse_heartbeat(heartbeat_bytes(bind=bind))
    assert payload["bind"] == bind


# -- HeartbeatReader: non-blocking read path -------------------------------------


def test_reader_feeds_tracker_from_fake_socket():
    tracker = HeartbeatTracker()
    reader = HeartbeatReader(tracker)
    sock = FakeSocket([heartbeat_bytes(revision=5), b"garbage", heartbeat_bytes(revision=6)])
    accepted = reader.poll(sock)
    assert accepted == 2
    assert tracker.revision == 6
    assert tracker.invalid_count == 1  # the garbage was counted, not dropped silently


def test_reader_returns_zero_on_empty_queue():
    reader = HeartbeatReader(HeartbeatTracker())
    assert reader.poll(FakeSocket([])) == 0


def test_reader_never_raises_on_broken_socket():
    reader = HeartbeatReader(HeartbeatTracker())
    assert reader.poll(BrokenSocket()) == 0


# -- frozen seam: the backend exposes the tracker and feeds it on the send socket --


class IdleBackend(CaptureBackend):
    """Backend whose run_loop just waits: the test drives send_packet directly."""

    def run_loop(self) -> None:
        self._stop_event.wait()


def make_packet(index: int) -> Packet:
    return Packet(t=index, engine="test", conf=1.0, pose=VALID_POSE, shapes={"jawOpen": 0.5})


def test_heartbeat_is_none_before_start():
    backend = IdleBackend(udp_host="127.0.0.1", udp_port=0)
    try:
        assert backend.heartbeat is None
    finally:
        backend.stop()


def test_heartbeat_exposed_after_start_and_cleared_on_stop():
    backend = IdleBackend(udp_host="127.0.0.1", udp_port=0)
    backend.start()
    try:
        assert isinstance(backend.heartbeat, HeartbeatTracker)
    finally:
        backend.stop()
    assert backend.heartbeat is None


def test_end_to_end_reply_on_the_same_socket_pair():
    # The "addon" end: a real UDP socket that receives packets and answers
    # the address recvfrom returned, like addon/receiver.py does.
    addon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    addon.bind(("127.0.0.1", 0))
    addon.settimeout(2.0)
    backend = IdleBackend(udp_host="127.0.0.1", udp_port=addon.getsockname()[1])
    backend.start()
    try:
        backend.send_packet(make_packet(1))
        data, sender_addr = addon.recvfrom(65535)
        assert b"rc_heartbeat" not in data  # outbound packet format untouched
        addon.sendto(heartbeat_bytes(revision=11), sender_addr)

        # The backend sees the reply on its next packet send (non-blocking).
        deadline = time.monotonic() + 2.0
        while backend.heartbeat.age_s() is None and time.monotonic() < deadline:
            backend.send_packet(make_packet(2))
            time.sleep(0.02)

        assert backend.heartbeat.age_s() is not None
        assert backend.heartbeat.revision == 11
        assert backend.heartbeat.bind_report() == BIND
        assert backend.heartbeat.invalid_count == 0
    finally:
        backend.stop()
        addon.close()

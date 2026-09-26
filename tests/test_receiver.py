"""Unit tests for the pure UDP receiver logic (real sockets, no bpy)."""

import socket
import time

import pytest

from backend.common.packets import encode_packet
from addon.receiver import UdpReceiver

VALID_POSE = {
    "rx": 0.0,
    "ry": 0.0,
    "rz": 0.0,
    "tx": 0.0,
    "ty": 0.0,
    "tz": 0.0,
}


def make_packet(t: int, jaw: float = 0.5) -> bytes:
    return encode_packet(t=t, engine="mediapipe", conf=1.0, pose=VALID_POSE, shapes={"jawOpen": jaw})


@pytest.fixture()
def receiver():
    rx = UdpReceiver(host="127.0.0.1", port=0)  # port 0: OS assigns an ephemeral port
    yield rx
    rx.close()


def _send_to(receiver: UdpReceiver, payloads: list[bytes]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for payload in payloads:
            sock.sendto(payload, ("127.0.0.1", receiver.bound_port))
    # Give the loopback a beat so datagrams land in the queue.
    time.sleep(0.05)


def test_empty_poll_returns_none(receiver):
    assert receiver.poll_latest() is None


def test_single_packet_roundtrip(receiver):
    _send_to(receiver, [make_packet(100)])
    packet = receiver.poll_latest()
    assert packet is not None
    assert packet.t == 100
    assert packet.shapes["jawOpen"] == pytest.approx(0.5)


def test_latest_frame_wins(receiver):
    _send_to(receiver, [make_packet(100, 0.1), make_packet(200, 0.2), make_packet(300, 0.3)])
    packet = receiver.poll_latest()
    assert packet is not None
    assert packet.t == 300
    assert packet.shapes["jawOpen"] == pytest.approx(0.3)
    # Queue was drained: nothing left.
    assert receiver.poll_latest() is None


def test_stale_frames_dropped_between_polls(receiver):
    _send_to(receiver, [make_packet(100)])
    first = receiver.poll_latest()
    assert first is not None and first.t == 100
    _send_to(receiver, [make_packet(500)])
    second = receiver.poll_latest()
    assert second is not None and second.t == 500


def test_invalid_packet_counted_when_newest(receiver):
    _send_to(receiver, [b"{not json"])
    assert receiver.poll_latest() is None
    assert receiver.invalid_count == 1


def test_newest_valid_wins_over_stale_invalid(receiver):
    # Only the newest datagram is decoded (documented semantics): a stale
    # invalid datagram is discarded without decode cost.
    _send_to(receiver, [b"{not json", make_packet(400)])
    packet = receiver.poll_latest()
    assert packet is not None
    assert packet.t == 400
    assert receiver.invalid_count == 0


def test_only_invalid_packets_returns_none(receiver):
    _send_to(receiver, [b"garbage"])
    assert receiver.poll_latest() is None
    assert receiver.invalid_count == 1


def test_invalid_port_rejected():
    with pytest.raises(ValueError):
        UdpReceiver(host="127.0.0.1", port=70000)


def test_stale_discards_counted_per_drain(receiver):
    """Every drained datagram replaced by a newer one is a stale discard."""
    _send_to(receiver, [make_packet(100, 0.1), make_packet(200, 0.2), make_packet(300, 0.3)])
    packet = receiver.poll_latest()
    assert packet is not None and packet.t == 300
    # Three drained, only the newest kept: two stale discards.
    assert receiver.stale_dropped == 2
    # An empty poll after the drain must not increment the counter.
    assert receiver.poll_latest() is None
    assert receiver.stale_dropped == 2


def test_single_datagram_poll_discards_nothing(receiver):
    """A poll that drains exactly one datagram discards nothing."""
    _send_to(receiver, [make_packet(100)])
    packet = receiver.poll_latest()
    assert packet is not None
    assert receiver.stale_dropped == 0


def test_empty_poll_does_not_increment_stale_dropped(receiver):
    """A poll that receives nothing must not increment the counter."""
    assert receiver.poll_latest() is None
    assert receiver.stale_dropped == 0


def test_stale_counter_is_cumulative_across_polls(receiver):
    """The counter accumulates over the receiver's lifetime."""
    _send_to(receiver, [make_packet(100), make_packet(200)])
    assert receiver.poll_latest() is not None
    assert receiver.stale_dropped == 1
    _send_to(receiver, [make_packet(300), make_packet(400), make_packet(500)])
    assert receiver.poll_latest() is not None
    assert receiver.stale_dropped == 3


def test_stale_invalid_newest_is_invalid_not_stale(receiver):
    """The newest datagram is decoded (invalid if bad); only the older drained
    datagrams are stale discards."""
    _send_to(receiver, [make_packet(100), b"{not json"])
    assert receiver.poll_latest() is None
    assert receiver.invalid_count == 1
    assert receiver.stale_dropped == 1


def test_reset_counters_zeroes_both_cumulative_counters(receiver):
    """reset_counters() clears stale_dropped and invalid_count together."""
    _send_to(receiver, [make_packet(100), make_packet(200)])
    assert receiver.poll_latest() is not None
    _send_to(receiver, [b"{not json"])
    assert receiver.poll_latest() is None
    assert receiver.stale_dropped == 1
    assert receiver.invalid_count == 1
    receiver.reset_counters()
    assert receiver.stale_dropped == 0
    assert receiver.invalid_count == 0

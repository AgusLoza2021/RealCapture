"""Unit tests for session record/replay (pure logic, no bpy)."""

import json

import pytest

from addon.schema import encode_packet
from addon.session import (
    SESSION_HEADER_KIND,
    SESSION_FORMAT_VERSION,
    ReplayScheduler,
    SessionError,
    SessionRecorder,
    read_session,
)

VALID_POSE = {"rx": 0.0, "ry": 0.0, "rz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0}


def make_packet(t: int, jaw: float = 0.5) -> bytes:
    return encode_packet(t=t, engine="mediapipe", conf=1.0, pose=VALID_POSE, shapes={"jawOpen": jaw})


def decode(payload: bytes):
    from addon.schema import decode_packet

    return decode_packet(payload)


@pytest.fixture()
def recorder(tmp_path):
    rec = SessionRecorder(tmp_path / "session.jsonl")
    rec.start()
    yield rec
    if rec.is_recording:
        rec.stop()


def test_record_and_read_roundtrip(recorder):
    for i in range(5):
        recorder.record(decode(make_packet(1000 + i, jaw=i / 10)), recv_epoch_ms=5000 + i * 33)
    recorder.stop()

    entries, skipped = read_session(recorder.path)
    assert skipped == 0
    assert len(entries) == 5
    assert [t for t, _ in entries] == [5000 + i * 33 for i in range(5)]
    assert entries[3][1].shapes["jawOpen"] == pytest.approx(0.3)
    assert entries[0][1].t == 1000


def test_header_line_written(recorder):
    recorder.record(decode(make_packet(1)), 1)
    recorder.stop()
    first_line = recorder.path.read_text(encoding="utf-8").splitlines()[0]
    header = json.loads(first_line)
    assert header == {"v": SESSION_FORMAT_VERSION, "kind": SESSION_HEADER_KIND}


def test_read_rejects_non_session_file(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"something": "else"}) + "\n", encoding="utf-8")
    with pytest.raises(SessionError):
        read_session(bad)


def test_read_skips_malformed_lines(tmp_path):
    good = json.dumps({"recv_t": 10, "packet": json.loads(make_packet(10).decode())})
    path = tmp_path / "mixed.jsonl"
    path.write_text(
        json.dumps({"v": 1, "kind": SESSION_HEADER_KIND})
        + "\n{not json\n"
        + json.dumps({"recv_t": "oops", "packet": {}})
        + "\n"
        + json.dumps({"packet": json.loads(make_packet(20).decode())})  # missing recv_t
        + "\n"
        + good
        + "\n",
        encoding="utf-8",
    )
    entries, skipped = read_session(path)
    assert skipped == 3
    assert len(entries) == 1
    assert entries[0][1].t == 10


def test_recorder_requires_start():
    rec = SessionRecorder("unused.jsonl")
    with pytest.raises(RuntimeError):
        rec.record(decode(make_packet(1)), 1)


def test_recorder_flushes_periodically(tmp_path):
    rec = SessionRecorder(tmp_path / "flush.jsonl", flush_every=2)
    rec.start()
    for i in range(4):
        rec.record(decode(make_packet(i)), i)
    # After 4 records with flush_every=2 the file must already contain data.
    assert len(rec.path.read_text(encoding="utf-8").splitlines()) >= 4
    rec.stop()


def test_scheduler_preserves_timing():
    entries = [(100, decode(make_packet(1))), (133, decode(make_packet(2))), (300, decode(make_packet(3)))]
    sched = ReplayScheduler(entries)
    assert sched.duration_ms == 200

    sched.start(now_monotonic_ms=10_000.0)
    # The first entry is due immediately (elapsed == 0).
    assert [p.t for p in sched.poll(10_000.0)] == [1]
    assert not sched.exhausted

    # 100 ms after start: next entry due (recv_t - first <= elapsed).
    due = sched.poll(10_099.9)
    assert [p.t for p in due] == [2]
    due = sched.poll(10_300.0)
    assert len(due) == 1
    assert sched.exhausted


def test_scheduler_rejects_empty():
    with pytest.raises(ValueError):
        ReplayScheduler([])


def test_scheduler_sorts_unordered_entries():
    entries = [(300, decode(make_packet(3))), (100, decode(make_packet(1)))]
    sched = ReplayScheduler(entries)
    sched.start(0.0)
    due = sched.poll(10_000.0)
    assert [p.t for p in due] == [1, 3]

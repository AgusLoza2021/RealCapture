"""Tests for the served dashboard UI (work unit W5).

The page is a single static HTML file with inline CSS/JS and no external
dependency. These tests assert the served document carries the honesty
contract's structure: a camera panel wired to the MJPEG stream, a
connection-list container, per-row state text (never colour-only), an
explicit UNKNOWN state, reason placeholders, a first-run empty state, and
no external URL of any kind.

The JS rendering itself is not executed here: no browser is opened.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from backend.dashboard.hub import BroadcastHub, DashboardHub  # noqa: E402
from backend.dashboard.server import create_app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(create_app(DashboardHub(), BroadcastHub())) as test_client:
        yield test_client


def _index_html(client) -> str:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    return response.text


class TestDashboardUIServed:
    def test_index_answers_200_html(self, client) -> None:
        assert _index_html(client)  # non-empty document

    def test_camera_panel_is_wired_to_the_mjpeg_stream(self, client) -> None:
        html = _index_html(client)
        assert 'id="camera-img"' in html
        assert "/camera.mjpg" in html

    def test_connection_list_container_is_present(self, client) -> None:
        assert 'id="connections"' in _index_html(client)

    def test_per_row_state_is_printed_as_text_not_only_colour(self, client) -> None:
        html = _index_html(client)
        assert 'class="state"' in html
        for word in ("GREEN", "YELLOW", "RED"):
            assert word in html

    def test_unknown_state_is_explicit_in_the_page(self, client) -> None:
        assert "UNKNOWN" in _index_html(client)

    def test_reason_placeholder_is_present(self, client) -> None:
        assert 'class="reason"' in _index_html(client)

    def test_first_run_empty_state_gives_plain_instructions(self, client) -> None:
        html = _index_html(client)
        assert "run_capture.py" in html
        assert "Blender" in html

    def test_no_external_dependency_of_any_kind(self, client) -> None:
        html = _index_html(client)
        assert "http://" not in html
        assert "https://" not in html

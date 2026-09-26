"""Pure tests for the mediapipe ``BaseOptions`` layout resolver.

These tests must run with mediapipe NOT installed: they feed stub module
objects shaped like the namespaces of mediapipe 0.10.x and 1.x. The resolver
is a module-level pure function with no side effects and no real mediapipe
import at module scope.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.backends.mediapipe_backend import resolve_base_options


class _FakeBaseOptions:
    """Sentinel class standing in for mediapipe.tasks...BaseOptions."""


def _mediapipe_stub(
    *,
    tasks_python_base_options: type | None = None,
    tasks_base_options: type | None = None,
    tasks_vision_base_options: type | None = None,
    version: str = "0.0.0-stub",
) -> SimpleNamespace:
    """Build a mediapipe-like module object from explicit layout pieces."""
    tasks = SimpleNamespace()
    if tasks_python_base_options is not None:
        tasks.python = SimpleNamespace(BaseOptions=tasks_python_base_options)
    if tasks_base_options is not None:
        tasks.BaseOptions = tasks_base_options
    if tasks_vision_base_options is not None:
        tasks.vision = SimpleNamespace(BaseOptions=tasks_vision_base_options)
    return SimpleNamespace(tasks=tasks, __version__=version)


def test_resolves_canonical_tasks_python_base_options():
    """1.x layout exposing only mediapipe.tasks.python.BaseOptions."""
    mp = _mediapipe_stub(tasks_python_base_options=_FakeBaseOptions)
    assert resolve_base_options(mp) is _FakeBaseOptions


def test_resolves_tasks_level_alias():
    """Real 1.0.1 layout: BaseOptions re-exported at mediapipe.tasks level."""
    mp = _mediapipe_stub(tasks_base_options=_FakeBaseOptions)
    assert resolve_base_options(mp) is _FakeBaseOptions


def test_resolves_legacy_tasks_vision_base_options():
    """0.10.x layout exposing only mediapipe.tasks.vision.BaseOptions."""
    mp = _mediapipe_stub(tasks_vision_base_options=_FakeBaseOptions)
    assert resolve_base_options(mp) is _FakeBaseOptions


def test_prefers_canonical_location_over_legacy():
    """Canonical mediapipe.tasks.python location wins when several exist."""
    class _Canonical(_FakeBaseOptions):
        pass

    class _Legacy(_FakeBaseOptions):
        pass

    mp = _mediapipe_stub(
        tasks_python_base_options=_Canonical,
        tasks_base_options=_Canonical,
        tasks_vision_base_options=_Legacy,
    )
    assert resolve_base_options(mp) is _Canonical


def test_missing_everywhere_raises_actionable_error():
    """Broken namespace: error names the version and every location tried."""
    mp = _mediapipe_stub(version="9.9.9-broken")
    with pytest.raises(AttributeError) as excinfo:
        resolve_base_options(mp)
    message = str(excinfo.value)
    assert "9.9.9-broken" in message
    assert "mediapipe.tasks.python.BaseOptions" in message
    assert "mediapipe.tasks.BaseOptions" in message
    assert "mediapipe.tasks.vision.BaseOptions" in message

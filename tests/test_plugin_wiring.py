"""Structural wiring tests for the Blender plugin (no bpy import: ast only).

Gates: the three new operator ids exist and are unique, every pre-existing
bl_idname is preserved, ``unregister`` stops the child this addon started,
``_tick`` guards itself with try/except, ``addon/__init__.py`` registers
``preferences`` before ``ui``, ``addon/preferences.py`` carries
``bl_idname = __package__``, and no file under ``addon/`` ever uses
``shell=True``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = REPO_ROOT / "addon"
UI = ADDON_DIR / "ui.py"
INIT = ADDON_DIR / "__init__.py"
PREFERENCES = ADDON_DIR / "preferences.py"

NEW_BL_IDNAMES = (
    "realcapture.start_backend",
    "realcapture.stop_backend",
    "realcapture.open_control_room",
)

# The ids ui.py had before the cockpit landed; these must keep working.
PRE_EXISTING_UI_BL_IDNAMES = (
    "realcapture.start_capture",
    "realcapture.stop_capture",
    "realcapture.replay_session",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _module_level_assignments(tree: ast.Module) -> dict[str, ast.expr]:
    assignments: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments[node.target.id] = node.value
    return assignments


def _class_tree(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


def _bl_idnames(tree: ast.Module) -> list[str]:
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if (
                    isinstance(child, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "bl_idname" for t in child.targets)
                    and isinstance(child.value, ast.Constant)
                ):
                    values.append(child.value.value)
    return values


def test_ui_defines_the_three_new_bl_idnames():
    ids = _bl_idnames(_tree(UI))
    for expected in NEW_BL_IDNAMES:
        assert expected in ids


def test_ui_bl_idnames_are_unique():
    ids = _bl_idnames(_tree(UI))
    assert len(ids) == len(set(ids))


def test_ui_keeps_every_pre_existing_bl_idname():
    ids = _bl_idnames(_tree(UI))
    for expected in PRE_EXISTING_UI_BL_IDNAMES:
        assert expected in ids


def test_ui_unregister_stops_the_process():
    unregister = _functions(_tree(UI))["unregister"]
    source = ast.unparse(unregister)
    assert "_process" in source
    assert ".stop(" in source


def test_ui_unregister_removes_the_timer_and_stops_the_poller():
    source = ast.unparse(_functions(_tree(UI))["unregister"])
    assert "unregister(_tick)" in source or "timers.unregister" in source
    assert "_poller" in source


def test_ui_tick_guards_itself_with_try_except():
    tick = _functions(_tree(UI))["_tick"]
    handlers = [
        node
        for node in ast.walk(tick)
        if isinstance(node, ast.Try) and node.handlers
    ]
    assert handlers, "_tick must wrap its body in try/except"


def test_ui_tick_returns_the_cockpit_decision():
    source = ast.unparse(_functions(_tree(UI))["_tick"])
    assert "next_tick_interval" in source


def test_ui_keeps_the_lazy_consumer_singleton():
    # tools/blender_mpfb_live.py imports _get_consumer from addon.ui.
    functions = _functions(_tree(UI))
    assert "_get_consumer" in functions


def test_ui_has_module_level_process_and_poller_state():
    assignments = _module_level_assignments(_tree(UI))
    assert "_process" in assignments
    assert "_poller" in assignments


def test_ui_register_starts_the_timer():
    register_source = ast.unparse(_functions(_tree(UI))["register"])
    assert "_ensure_timer()" in register_source
    assert "timers.register" in ast.unparse(_tree(UI))  # inside _ensure_timer


def test_init_registers_preferences_before_ui():
    register = _functions(_tree(INIT))["register"]
    names = [
        node.func.value.id
        for node in ast.walk(register)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register"
        and isinstance(node.func.value, ast.Name)
    ]
    assert "properties" in names
    assert "preferences" in names
    assert "ui" in names
    assert names.index("preferences") < names.index("ui")


def test_init_unregisters_ui_before_preferences():
    unregister = _functions(_tree(INIT))["unregister"]
    names = [
        node.func.value.id
        for node in ast.walk(unregister)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "unregister"
        and isinstance(node.func.value, ast.Name)
    ]
    assert names.index("ui") < names.index("preferences")


def test_preferences_class_binds_bl_idname_to_package():
    tree = _tree(PREFERENCES)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    assert len(classes) == 1
    prefs_class = classes[0]
    bound = [
        stmt.value
        for stmt in prefs_class.body
        if isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "bl_idname" for t in stmt.targets)
    ]
    assert len(bound) == 1
    assert isinstance(bound[0], ast.Name) and bound[0].id == "__package__"


def test_preferences_defines_exactly_the_six_frozen_fields():
    tree = _tree(PREFERENCES)
    prefs_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef)
    )
    names = {
        target.id
        for stmt in prefs_class.body
        if isinstance(stmt, (ast.Assign, ast.AnnAssign))
        for target in (
            stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        )
        if isinstance(target, ast.Name)
    }
    assert names == {
        "bl_idname",
        "repo_root",
        "python_executable",
        "udp_port",
        "dashboard_port",
        "camera_index",
        "open_browser_on_start",
    }


def test_no_addon_file_uses_shell_true():
    offenders = []
    for path in sorted(ADDON_DIR.rglob("*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (
                        keyword.arg == "shell"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True
                    ):
                        offenders.append(path.name)
    assert offenders == []


def test_preferences_draw_renders_every_frozen_field():
    """A preferences class with no draw() is invisible in Blender's UI.

    repo_root is the one value the user must set before anything can start, so
    the panel must render all six fields, not a subset.
    """
    classes = _class_tree(_tree(PREFERENCES))
    prefs = classes["RealCapturePreferences"]
    draw = next(
        (
            node
            for node in prefs.body
            if isinstance(node, ast.FunctionDef) and node.name == "draw"
        ),
        None,
    )
    assert draw is not None, "RealCapturePreferences has no draw()"
    # layout.prop(self, "repo_root") carries the field name as a STRING, so
    # both shapes count: self.<attr> and the plain string literals.
    rendered = {
        node.attr
        for node in ast.walk(draw)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    } | {
        node.value
        for node in ast.walk(draw)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert rendered >= {
        "repo_root",
        "python_executable",
        "udp_port",
        "dashboard_port",
        "camera_index",
        "open_browser_on_start",
    }

def test_stop_operator_obeys_the_pure_decision():
    """ui.py cannot be imported here (bpy), so the stop operator's shape is gated.

    The defect this rejects: clearing ``_process`` unconditionally, which shows
    "not started" while the child may still be alive. The assignment must sit
    inside an ``if`` whose test asks the pure decision.
    """
    operator = _class_tree(_tree(UI))["RC_OT_stop_backend"]
    execute = next(
        node
        for node in operator.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute"
    )
    unconditional = [
        node
        for node in execute.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_process" for t in node.targets)
    ]
    assert unconditional == [], "the stop operator clears _process unconditionally"
    guarded = [
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.If)
        and "stop_clears_state" in ast.dump(node.test)
        and any(
            isinstance(child, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_process" for t in child.targets)
            for child in node.body
        )
    ]
    assert guarded, "the stop operator does not consult stop_clears_state()"

def test_no_staticmethod_uses_self():
    """A @staticmethod whose body reads ``self`` raises NameError at draw time.

    Found the hard way: ``_draw_pipeline`` was a staticmethod that called
    ``self._draw_health_row``, so the panel raised the first time a human
    opened the N sidebar. pytest never draws, so only a structural gate in
    this file can catch it.
    """
    offenders = []
    for path in sorted(ADDON_DIR.rglob("*.py")):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {
                d.id for d in node.decorator_list if isinstance(d, ast.Name)
            }
            if "staticmethod" not in decorators:
                continue
            used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            parameters = {a.arg for a in node.args.args}
            if "self" in used and "self" not in parameters:
                offenders.append(f"{path.name}:{node.lineno}:{node.name}")
    assert offenders == []

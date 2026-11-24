"""Config / registry unit tests (no display needed):  pytest tests/test_config.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from like_potplayer import actions, config


def cfg(tmp_path, **files):
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data))
    return config.Config(str(tmp_path))


def test_defaults_clean(tmp_path):
    c = cfg(tmp_path)
    assert c.errors == [] and len(c.hotkeys) > 50 and c.app_name == "like_potplayer"
    assert Path(c.icon_path("app")).is_file()


def test_user_rebind_and_unbind(tmp_path):
    c = cfg(tmp_path, hotkeys={"schema": 1, "bindings": [
        {"action": "toggle_pause", "keys": ["K"]}, {"action": "toggle_eq", "keys": []}]})
    keys = {b["action"]: b["keys"] for b in c.hotkeys}
    assert keys["toggle_pause"] == ["K"] and "toggle_eq" not in keys


def test_same_action_different_args_are_separate(tmp_path):
    c = cfg(tmp_path)
    seeks = [b for b in c.hotkeys if b["action"] == "seek"]
    assert {tuple(b["args"]) for b in seeks} == {(-5,), (5,), (-30,), (30,)}


def test_validation_errors(tmp_path):
    c = cfg(tmp_path, hotkeys={"schema": 1, "bindings": [
        {"action": "nope", "keys": ["F9"]}, {"action": "seek", "args": ["x"], "keys": ["F8"]},
        {"action": "seek", "keys": ["F8"]}]})
    assert len(c.errors) == 3


def test_bad_json_reports_line(tmp_path):
    (tmp_path / "hotkeys.json").write_text('{\n "schema": 1,\n "bindings": [,]\n}')
    c = config.Config(str(tmp_path))
    assert any("hotkeys.json:3" in e for e in c.errors)


def test_branding_override_and_relative_icon(tmp_path):
    (tmp_path / "my.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    c = cfg(tmp_path, branding={"schema": 1, "app_name": "Foo", "window_title_format": "{app_name}: {title}",
                                "icons": {"app": "my.svg"}})
    assert c.app_name == "Foo" and c.title_for("x") == "Foo: x" and c.icon_path("app") == str(tmp_path / "my.svg")


def test_macros(tmp_path):
    c = cfg(tmp_path, commands={"schema": 1, "macros": {"jump90": [{"action": "seek", "args": [90]}]}},
            hotkeys={"schema": 1, "bindings": [{"action": "jump90", "keys": ["F9"]}]})
    assert c.errors == [] and any(b["action"] == "jump90" for b in c.hotkeys)


def test_every_default_action_exists_on_player():
    actions.set_macros({})
    src = (Path(__file__).resolve().parent.parent / "like_potplayer" / "app.py").read_text()
    missing = [a for a in actions.ids() if f"def a_{a}(" not in src and a not in ("preferences",)
               and f"a_{a} =" not in src and f"def a_{a}(" not in src]
    # a few actions are defined as one-liners (def a_x(self): ...) which the pattern above still matches
    assert missing == [], missing

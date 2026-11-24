"""
Layered JSON configuration for like_potplayer.

Order (later wins, key by key):  built-in defaults  <  user config dir  <  --config DIR / $LIKE_POTPLAYER_CONFIG
Files: branding.json, hotkeys.json, mouse.json, associations.json, commands.json (user only).
"""
import copy
import json
import os
import sys
from pathlib import Path

from . import actions

PKG_DIR = Path(__file__).resolve().parent
DEFAULTS_DIR = PKG_DIR / "defaults"
DEFAULT_APP_ID = "like_potplayer"
SCHEMA = 1


def exe_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PKG_DIR.parent


def config_dir(override=None, app_id=DEFAULT_APP_ID):
    """User config directory. Portable mode: a file named portable.flag next to the program -> ./data"""
    if override or os.environ.get("LIKE_POTPLAYER_CONFIG"):
        return Path(override or os.environ["LIKE_POTPLAYER_CONFIG"]).expanduser()
    if (exe_dir() / "portable.flag").exists():
        return exe_dir() / "data"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_id
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_id
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / app_id


def skin_dirs(cfg_dir):
    """Bundled skins/ (next to the project or executable), then the user skins/ directory."""
    return [exe_dir() / "skins", Path(cfg_dir) / "skins"]


def _deep_merge(a, b):
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    def __init__(self, override=None):
        self.override = override
        self.dir = config_dir(override)
        self.errors = []
        self.reload()

    # ---- loading
    def _read(self, path):
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            self.errors.append(f"{path}:{e.lineno}: {e.msg}")
            return None
        except OSError as e:
            self.errors.append(f"{path}: {e}")
            return None
        if not isinstance(data, dict):
            self.errors.append(f"{path}: top level must be an object")
            return None
        if data.get("schema", SCHEMA) != SCHEMA:
            self.errors.append(f"{path}: unsupported schema {data.get('schema')} (expected {SCHEMA})")
            return None
        return data

    def _abs_icons(self, data, base):
        icons = data.get("icons")
        if not isinstance(icons, dict):
            return data

        def fix(v):
            if isinstance(v, str):
                p = Path(v).expanduser()
                return str(p if p.is_absolute() else (base / p))
            if isinstance(v, dict):
                return {k: fix(x) for k, x in v.items()}
            return v
        data["icons"] = fix(icons)
        return data

    def reload(self):
        self.errors = []
        d = self._read(DEFAULTS_DIR / "branding.json") or {}
        d = self._abs_icons(d, DEFAULTS_DIR)
        u = self._read(self.dir / "branding.json")
        if u:
            d = _deep_merge(d, self._abs_icons(u, self.dir))
        self.branding = d
        self.macros = (self._read(self.dir / "commands.json") or {}).get("macros", {})
        actions.set_macros(self.macros)          # macros first: hotkeys may refer to them
        self.hotkeys = self._bindings("hotkeys.json", "keys")
        self.mouse = self._bindings("mouse.json", "gesture")
        self.assoc = _deep_merge(self._read(DEFAULTS_DIR / "associations.json") or {},
                                 self._read(self.dir / "associations.json") or {})

    def _bindings(self, name, field):
        merged = {}
        for src in (DEFAULTS_DIR / name, self.dir / name):
            data = self._read(src)
            if not data:
                continue
            for i, b in enumerate(data.get("bindings", [])):
                why = self._check(b, field)
                if why:
                    self.errors.append(f"{src} binding #{i + 1}: {why}")
                    continue
                key = (b["action"], json.dumps(b.get("args", [])), b.get("gesture") if field == "gesture" else None)
                merged[key] = b
        return [b for b in merged.values()
                if (b.get("keys") if field == "keys" else b.get("gesture"))]

    def _check(self, b, field):
        if not isinstance(b, dict) or not isinstance(b.get("action"), str):
            return "needs an 'action' string"
        if not actions.known(b["action"]):
            return f"unknown action '{b['action']}' (see --list-actions)"
        args = b.get("args", [])
        if not isinstance(args, list):
            return "'args' must be a list"
        err = actions.check_args(b["action"], args)
        if err:
            return err
        if field == "keys" and not isinstance(b.get("keys", []), list):
            return "'keys' must be a list"
        if field == "gesture" and not isinstance(b.get("gesture"), str):
            return "needs a 'gesture' string"
        return None

    # ---- accessors
    @property
    def app_id(self):
        return self.branding.get("app_id", DEFAULT_APP_ID)

    @property
    def app_name(self):
        return self.branding.get("app_name", "like_potplayer")

    def title_for(self, media_title):
        fmt = self.branding.get("window_title_format", "{title} - {app_name}")
        try:
            return fmt.format(title=media_title, app_name=self.app_name)
        except (KeyError, IndexError, ValueError):
            return f"{media_title} - {self.app_name}"

    def icon_path(self, name="app"):
        p = self.branding.get("icons", {}).get(name)
        if isinstance(p, str) and Path(p).is_file():
            return p
        return None

    def ui_icon_path(self, name):
        p = self.branding.get("icons", {}).get("ui", {}).get(name)
        return p if isinstance(p, str) and Path(p).is_file() else None

    def save_hotkeys(self, bindings):
        """Write the full effective list to the user's hotkeys.json (used by the in-app editor)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "hotkeys.json").write_text(
            json.dumps({"schema": SCHEMA, "bindings": bindings}, indent=2) + "\n", encoding="utf-8")

    def effective(self):
        return {"config_dir": str(self.dir), "errors": self.errors, "branding": self.branding,
                "hotkeys": self.hotkeys, "mouse": self.mouse, "associations": self.assoc,
                "macros": self.macros}

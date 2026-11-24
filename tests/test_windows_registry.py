"""
Windows registration logic, tested on any OS with a fake `winreg`:
  * `like_potplayer --register-defaults` writes the expected keys and --unregister-defaults removes them
  * the installer's generated [Registry] entries (tools/gen_iss.py) are the same keys, so both paths agree
"""
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from like_potplayer import associations, config  # noqa: E402


class FakeWinreg(types.ModuleType):
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        super().__init__("winreg")
        self.store = {}

    def CreateKey(self, root, path):
        self.store.setdefault(path.lower(), {})
        reg = self

        class K:
            def __enter__(s):
                return path.lower()

            def __exit__(s, *a):
                return False
        return K()

    def SetValueEx(self, key, name, _r, _t, value):
        self.store[key][name] = value

    def DeleteKey(self, root, path):
        for k in [k for k in self.store if k == path.lower() or k.startswith(path.lower() + "\\")]:
            del self.store[k]


def _fake(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("os.startfile", lambda *_: None, raising=False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)      # shutil.which misbehaves with a faked platform
    return fake


def test_register_and_unregister(monkeypatch, tmp_path):
    fake = _fake(monkeypatch)
    cfg = config.Config(str(tmp_path))
    msg = associations.register(cfg)
    assert "Default apps" in msg
    prog = f"{cfg.app_id}.Media"
    assert fake.store[rf"software\classes\{prog}\shell\open\command".lower()][""].endswith('"%1"')
    assert fake.store[r"software\classes\.mp4\openwithprogids"][prog] == ""
    assert fake.store[rf"software\{cfg.app_id}\capabilities\fileassociations"][".mkv"] == prog
    assert fake.store[r"software\registeredapplications"][cfg.app_id] == rf"Software\{cfg.app_id}\Capabilities"
    associations.unregister(cfg)
    assert not any(k.startswith(rf"software\classes\{prog}".lower()) or k.startswith(rf"software\{cfg.app_id}") for k in fake.store)


def test_installer_registry_matches_python_registration(monkeypatch, tmp_path):
    subprocess.run([sys.executable, str(ROOT / "tools" / "gen_iss.py")], check=True, capture_output=True)
    iss = (ROOT / "build" / "windows" / "registry.iss").read_text(encoding="utf-8")
    from_iss = set()
    for line in iss.splitlines():
        if not line.startswith("Root:"):
            continue
        sub = re.search(r'Subkey: "([^"]+)"', line).group(1).lower()
        name = re.search(r'ValueName: "([^"]*)"', line)
        from_iss.add((sub, name.group(1) if name else ""))
    fake = _fake(monkeypatch)
    associations.register(config.Config(str(tmp_path)))
    from_py = {(k, n) for k, vals in fake.store.items() for n in vals}
    assert from_iss == from_py, (sorted(from_iss - from_py)[:5], sorted(from_py - from_iss)[:5])


def test_installer_defines(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "tools" / "gen_iss.py")], check=True, capture_output=True)
    d = (ROOT / "build" / "windows" / "defines.iss").read_text()
    assert re.search(r'#define AppGuid "\{\{[0-9A-F-]{36}\}"', d) and '#define AppVersion "' in d


def test_msi_registry_matches_installer(tmp_path):
    """The MSI (HKLM) and the Inno installer (HKA) must register exactly the same keys and value names."""
    import xml.etree.ElementTree as ET
    for g in ("gen_iss.py", "gen_wxs.py"):
        subprocess.run([sys.executable, str(ROOT / "tools" / g)], check=True, capture_output=True)
    ns = "{http://wixtoolset.org/schemas/v4/wxs}"
    msi = {(v.get("Key").lower(), v.get("Name", "")) for v in ET.parse(ROOT / "build/windows/like_potplayer.wxs").getroot().iter(ns + "RegistryValue")}
    iss = set()
    for line in (ROOT / "build/windows/registry.iss").read_text().splitlines():
        if line.startswith("Root:"):
            n = re.search(r'ValueName: "([^"]*)"', line)
            iss.add((re.search(r'Subkey: "([^"]+)"', line).group(1).lower(), n.group(1) if n else ""))
    assert msi == iss, (sorted(msi - iss)[:3], sorted(iss - msi)[:3])

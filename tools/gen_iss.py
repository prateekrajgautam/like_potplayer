#!/usr/bin/env python3
"""
Generate the two Inno Setup include files used by packaging/windows/like_potplayer.iss:
  build/windows/defines.iss   - app name, id, version, stable AppId GUID (derived from app_id)
  build/windows/registry.iss  - the [Registry] section: ProgID + "Open with" + Default apps capabilities
The entries mirror what `like_potplayer --register-defaults` writes (tests/test_windows_registry.py checks this).
"""
import sys
import uuid
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tools"))
import regmodel  # noqa: E402

cfg, _ver = regmodel.load()
out = root / "build" / "windows"
out.mkdir(parents=True, exist_ok=True)
ver = _ver
guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{cfg.app_id}.like_potplayer")).upper()
(out / "defines.iss").write_text(
    f'#define AppName "{cfg.app_name}"\n#define AppId "{cfg.app_id}"\n#define AppVersion "{ver}"\n'
    f'#define AppGuid "{{{{{guid}}}"\n', encoding="utf-8")

R = []
for e in regmodel.entries(cfg):
    parts = ["Root: HKA", f'Subkey: "{e["subkey"]}"', "ValueType: string"]
    if e["name"] is not None:
        parts.append(f'ValueName: "{e["name"]}"')
    parts.append('ValueData: "%s"' % e["value"].replace('"', '""'))
    flag = "uninsdeletevalue" if e.get("valueonly") else ("uninsdeletekey" if e.get("root") else "")
    if flag:
        parts.append(f"Flags: {flag}")
    parts.append("Tasks: assoc")
    R.append("; ".join(parts))
(out / "registry.iss").write_text("[Registry]\n" + "\n".join(R) + "\n", encoding="utf-8")
print(f"wrote {out / 'defines.iss'} and {out / 'registry.iss'} ({len(R)} registry entries)")

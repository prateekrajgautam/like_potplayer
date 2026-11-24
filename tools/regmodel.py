"""Single description of the Windows file-association registry entries, shared by the Inno Setup (.iss) and
WiX (.wxs/.msi) generators. {app} is the install folder; {#AppName} the display name. Names of values: None = (Default)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from like_potplayer import associations, config  # noqa: E402

EXE = "like_potplayer.exe"


def entries(cfg):
    """List of dicts: subkey (under HKCU/HKLM, no hive), name, value, kind ('keyroot'/'value')."""
    prog = f"{cfg.app_id}.Media"
    cap = rf"Software\{cfg.app_id}\Capabilities"
    out = [
        dict(subkey=rf"Software\Classes\{prog}", name=None, value="{#AppName} media file", root=True),
        dict(subkey=rf"Software\Classes\{prog}\DefaultIcon", name=None, value=f'"{{app}}\\{EXE}",0'),
        dict(subkey=rf"Software\Classes\{prog}\shell\open\command", name=None, value=f'"{{app}}\\{EXE}" "%1"'),
        dict(subkey=cap, name="ApplicationName", value="{#AppName}", root=True),
        dict(subkey=cap, name="ApplicationDescription", value="PotPlayer-style media player"),
    ]
    for e in associations.enabled_exts(cfg):
        out.append(dict(subkey=rf"{cap}\FileAssociations", name=f".{e}", value=prog))
        out.append(dict(subkey=rf"Software\Classes\.{e}\OpenWithProgids", name=prog, value="", valueonly=True))
    out.append(dict(subkey=r"Software\RegisteredApplications", name=cfg.app_id, value=rf"Software\{cfg.app_id}\Capabilities",
                    valueonly=True))
    return out


def load():
    cfg = config.Config()
    ver = next(l.split('"')[1] for l in (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text().splitlines()
               if l.startswith("version"))
    return cfg, ver

#!/usr/bin/env python3
"""Print branding fields for build scripts:  python tools/brand.py app_name | app_id | version"""
import json, sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
d = json.loads((root / "like_potplayer" / "defaults" / "branding.json").read_text())
user = Path(sys.argv[2]) if len(sys.argv) > 2 else root / "branding.override.json"   # optional build-time override
if user.is_file():
    d.update(json.loads(user.read_text()))
key = sys.argv[1] if len(sys.argv) > 1 else "app_name"
if key == "version":
    import re
    print(re.search(r'version = "([^"]+)"', (root / "pyproject.toml").read_text()).group(1))
else:
    print(d.get(key, ""))

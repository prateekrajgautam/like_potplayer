"""Help python-mpv find a bundled / user-specified libmpv (frozen builds, portable installs).
Import this BEFORE `import mpv`. Override with LIKE_POTPLAYER_LIBMPV=/path/to/libmpv.*"""
import ctypes.util
import os
import sys
from pathlib import Path

NAMES = ("libmpv.so.2", "libmpv.so.1", "libmpv.so", "libmpv.2.dylib", "libmpv.dylib", "libmpv-2.dll", "mpv-2.dll")


def _candidates():
    yield os.environ.get("LIKE_POTPLAYER_LIBMPV")
    bases = [Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None,
             Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None,
             Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent]
    for b in bases:
        if b:
            for n in NAMES:
                yield b / n
                yield b / "Frameworks" / n
            for g in sorted(b.glob("libmpv.so*")) + sorted(b.glob("_internal/libmpv.so*")):   # any versioned name
                yield g


def setup():
    path = next((c for c in _candidates() if c and Path(c).is_file()), None)
    if not path:
        return None
    path = str(path)
    if sys.platform == "win32":
        os.environ["PATH"] = str(Path(path).parent) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(Path(path).parent))
    orig = ctypes.util.find_library
    ctypes.util.find_library = lambda name: path if str(name).lower().replace("lib", "", 1).startswith("mpv") else orig(name)
    return path


setup()

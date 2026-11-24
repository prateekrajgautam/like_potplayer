"""
The action (function) registry. Hotkeys, mouse gestures, skin buttons, menus and macros all call these.
Argument spec: list of 'number' / 'string'; a trailing '*' means "any number more of the previous kind".
"""
from collections import OrderedDict

# id: (group, argspec, description)
_A = OrderedDict()


def _g(group, rows):
    for aid, spec, desc in rows:
        _A[aid] = (group, spec, desc)


_g("Transport", [
    ("toggle_pause", [], "Play / pause"), ("stop", [], "Stop"), ("prev", [], "Previous file"),
    ("next", [], "Next file"), ("seek", ["number"], "Seek relative, seconds"),
    ("seek_fraction", ["number"], "Seek to 0..1 of the duration"), ("seek_start", [], "Back to start"),
    ("goto", [], "Ask for a time and jump there")])
_g("Audio", [
    ("volume", ["number"], "Change volume by delta"), ("set_volume", ["number"], "Set volume 0..130"),
    ("toggle_mute", [], "Mute / unmute"), ("audio_sync", ["number"], "Audio delay by delta seconds (0 = reset)"),
    ("toggle_eq", [], "Equalizer on/off"), ("toggle_normalize", [], "Volume normalizer on/off"),
    ("audio_menu", [], "Choose audio track")])
_g("Speed", [
    ("speed", ["number"], "Change speed by delta"), ("set_speed", ["number"], "Set speed"),
    ("speed_reset", [], "Speed back to 1.0x")])
_g("Video", [
    ("frame_forward", [], "Next frame"), ("frame_back", [], "Previous frame"),
    ("screenshot", [], "Save a screenshot"), ("screenshot_clipboard", [], "Copy a screenshot to the clipboard"),
    ("filter", ["string"], "Toggle filter D / S / B / T"), ("control_box", [], "Video control panel"),
    ("aspect_cycle", [], "Cycle aspect ratio"), ("mirror", [], "Mirror horizontally"),
    ("flip_vertical", [], "Flip vertically"), ("brightness", ["number"], "Brightness by delta"),
    ("contrast", ["number"], "Contrast by delta"), ("saturation", ["number"], "Saturation by delta"),
    ("colour", ["number"], "Hue by delta"), ("image_reset", [], "Reset picture adjustments")])
_g("Subtitles", [
    ("toggle_subs", [], "Subtitles on/off"), ("sub_sync", ["number"], "Subtitle delay by delta seconds (0 = reset)"),
    ("open_sub", [], "Load a subtitle file"), ("sub_menu", [], "Choose subtitle track")])
_g("Loop and marks", [
    ("ab_start", [], "Set A point"), ("ab_end", [], "Set B point"), ("ab_reset", [], "Clear A-B"),
    ("ab_toggle", [], "A-B loop on/off"), ("bookmark_add", [], "Add bookmark"),
    ("bookmark_next", [], "Next bookmark"), ("bookmark_prev", [], "Previous bookmark"),
    ("bookmark_clear", [], "Clear bookmarks of this file"), ("bookmark_list", [], "Bookmark list"),
    ("cycle_repeat", [], "Repeat off / all / one"), ("shuffle_toggle", [], "Shuffle on/off")])
_g("Files and playlist", [
    ("open_files", [], "Open file(s)"), ("open_folder", [], "Open folder"), ("open_url", [], "Open URL"),
    ("close_file", [], "Close current file"), ("toggle_playlist", [], "Show / hide playlist"),
    ("playlist_save", [], "Save playlist (.m3u8)"), ("playlist_load", [], "Load playlist")])
_g("Window", [
    ("toggle_fullscreen", [], "Fullscreen"), ("leave_fullscreen", [], "Leave fullscreen"),
    ("toggle_slim", [], "Slim (audio) mode"), ("toggle_chrome", [], "Skin on/off"),
    ("toggle_on_top", [], "Always on top"), ("minimize", [], "Minimize"), ("maximize", [], "Maximize"),
    ("restore", [], "Restore"), ("cycle_page", [], "Cycle the bar's info page"), ("quit", [], "Quit")])
_g("App", [
    ("preferences", [], "Preferences (keyboard, skins, associations)"), ("about", [], "About"),
    ("skin_next", [], "Next skin"), ("skin_set", ["string"], "Switch to a skin by name ('default' = built-in)"),
    ("reload_config", [], "Re-read the JSON config"), ("register_defaults", [], "Register as default player"),
    ("unregister_defaults", [], "Remove default-player registration"),
    ("mpv", ["string", "*"], "Run an mpv command, e.g. [\"set\",\"hwdec\",\"no\"] (run/subprocess blocked)")])

MPV_BLOCKED = {"run", "subprocess", "load-script", "load_script", "script-binding", "script-message-to"}
_MACROS = {}


def set_macros(m):
    _MACROS.clear()
    if isinstance(m, dict):
        _MACROS.update(m)


def known(aid):
    return aid in _A or aid in _MACROS


def macro(aid):
    return _MACROS.get(aid)


def check_args(aid, args):
    if aid in _MACROS:
        return None
    spec = _A[aid][1]
    variadic = spec[-1:] == ["*"]
    fixed = spec[:-2] if variadic else spec
    base = spec[-2] if variadic else None
    if len(args) < len(fixed) or (not variadic and len(args) > len(fixed)):
        return f"'{aid}' takes {len(fixed)}{'+' if variadic else ''} argument(s), got {len(args)}"
    for i, a in enumerate(args):
        want = fixed[i] if i < len(fixed) else base
        if want == "number" and not (isinstance(a, (int, float)) and not isinstance(a, bool)):
            return f"'{aid}' argument {i + 1} must be a number"
        if want == "string" and not isinstance(a, str):
            return f"'{aid}' argument {i + 1} must be a string"
    return None


def describe():
    lines = []
    for group in OrderedDict.fromkeys(g for g, _, _ in _A.values()):
        lines.append(f"[{group}]")
        for aid, (g, spec, desc) in _A.items():
            if g == group:
                sig = ", ".join(s for s in spec if s != "*") + (", ..." if "*" in spec else "")
                lines.append(f"  {aid}({sig})  - {desc}")
    if _MACROS:
        lines.append("[User macros]")
        lines += [f"  {k}  - macro of {len(v)} step(s)" for k, v in _MACROS.items()]
    return "\n".join(lines)


def ids():
    return list(_A) + list(_MACROS)


def label(aid):
    return _A[aid][2] if aid in _A else f"macro {aid}"

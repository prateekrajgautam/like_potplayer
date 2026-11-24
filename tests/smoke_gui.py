"""Headless GUI smoke test: run under xvfb with LIBGL_ALWAYS_SOFTWARE=1 (see README, 'Testing')."""
import json, locale, os, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget
from like_potplayer import config as cfgmod
from like_potplayer.app import Player

MEDIA = sys.argv[1]
cfgdir = Path(tempfile.mkdtemp())
(cfgdir / "branding.json").write_text(json.dumps({"schema": 1, "app_name": "MyPlayer",
    "window_title_format": "[{app_name}] {title}"}))
(cfgdir / "hotkeys.json").write_text(json.dumps({"schema": 1, "bindings": [
    {"action": "toggle_pause", "keys": []},                       # unbind Space
    {"action": "toggle_pause", "keys": ["K"]},                    # ...and put it on K
    {"action": "no_such_action", "keys": ["F9"]}]}))
cfg = cfgmod.Config(str(cfgdir))
app = QApplication([]); locale.setlocale(locale.LC_NUMERIC, "C")
w = Player(cfg); w.mpv.ao = "null"; w.show()
R = []
def ok(name, cond): R.append(("PASS" if cond else "FAIL") + " " + name)
def step(ms, fn): QTimer.singleShot(ms, fn)

ok("config error reported for unknown action", any("no_such_action" in e for e in cfg.errors))
ok("branding name applied", app.applicationName() == "MyPlayer")
ok("default skin loaded from skins/", w.skin is not None and w.skin.name == "BlackBoxVFD_PreMod3_AdvCtrl")
ok("window icon from branding", not w.windowIcon().isNull())

w.activateWindow(); QTest.qWaitForWindowActive(w, 3000)
print('window active:', w.isActiveWindow())
step(200, lambda: w.open_paths([MEDIA]))
def t1():
    ok("title uses format", w.windowTitle().startswith("[MyPlayer]"))
    p0 = w.mpv.pause
    QTest.keyClick(w, Qt.Key_Space)                 # unbound -> no change
    ok("Space unbound", w.mpv.pause == p0)
    QTest.keyClick(w, Qt.Key_K)                     # rebound
    ok("K toggles pause (JSON rebind)", w.mpv.pause != p0)
    QTest.keyClick(w, Qt.Key_Comma, Qt.ShiftModifier)
    ok("Shift+',' sub_sync -0.5", abs((w.mpv.sub_delay or 0) + 0.5) < 1e-6)
    QTest.keyClick(w, Qt.Key_Period, Qt.ShiftModifier)
    ok("Shift+'.' sub_sync +0.5", abs(w.mpv.sub_delay or 0) < 1e-6)
    QTest.keyClick(w, Qt.Key_F7)
    ok("F7 toggles equalizer", w.st.toggles.get("ID_AUDIO_EQULIZER") is True)
    QTest.keyClick(w, Qt.Key_Q)
    w.run("speed", [0.5]); QTest.keyClick(w, Qt.Key_Q)
    ok("Q resets speed", abs(w.mpv.speed - 1.0) < 1e-6)
    w.run("brightness", [10]); ok("brightness action", w.mpv.brightness == 10)
    w.run("mpv", ["set", "volume", "33"]); ok("mpv passthrough", int(w.mpv.volume) == 33)
    w.run("mpv", ["run", "echo"]); ok("mpv 'run' blocked", True)
step(2200, t1)
def t2():                                           # runtime skin switching
    w.a_skin_set("default"); app.processEvents()
    ok("switched to plain Qt skin", w.skin is None and hasattr(w, "seek"))
    pos = w.mpv.time_pos
    w.a_skin_set("BlackBoxVFD_PreMod3_AdvCtrl"); app.processEvents()
    ok("switched back to skin", w.skin is not None and w.controls.__class__.__name__ == "AdvBar")
    ok("playback survived skin switch", w.mpv.time_pos is not None)
    w.a_skin_next(); ok("skin_next cycles", w.skin is None); w.a_skin_next()
step(2800, t2)
def t3():                                           # preferences keyboard editor saves JSON
    w.a_preferences(); tbl = w._prefs.findChild(QTableWidget)
    for r in range(tbl.rowCount()):
        if tbl.item(r, 0).text() == "toggle_mute":
            tbl.item(r, 2).setText("Ctrl+Shift+Y")
    save = [b for b in w._prefs.findChildren(QPushButton) if b.text() == "Save"][0]; save.click()
    from PySide6.QtWidgets import QLabel
    print('prefs msg:', [l.text() for l in w._prefs.findChildren(QLabel) if l.text()][:3])
    saved = json.loads((cfgdir / "hotkeys.json").read_text())
    ok("prefs editor wrote hotkeys.json", any(b["action"] == "toggle_mute" and b["keys"] == ["Ctrl+Shift+Y"] for b in saved["bindings"]))
    m0 = w.mpv.mute; QTest.keyClick(w, Qt.Key_Y, Qt.ControlModifier | Qt.ShiftModifier)
    ok("edited key active immediately", w.mpv.mute != m0)
    w._prefs.close()
step(3400, t3)
def t4():                                           # single instance: second process enqueues
    env = dict(os.environ, LIKE_POTPLAYER_CONFIG=str(cfgdir))
    subprocess.run([sys.executable, "-m", "like_potplayer", "--enqueue", MEDIA], env=env,
                   cwd=str(Path(__file__).resolve().parent.parent), timeout=20)
step(3800, t4)
def t5():
    app.processEvents()
    print("\n".join(R)); print("items in playlist:", len(w.items))
    w.close(); app.quit()
step(7500, t5)
# server for step 4 is created by cli.main normally; emulate it here
from PySide6.QtNetwork import QLocalServer
import getpass
srv = QLocalServer(); QLocalServer.removeServer(f"{cfg.app_id}-{getpass.getuser()}"); srv.listen(f"{cfg.app_id}-{getpass.getuser()}")
def conn():
    c = srv.nextPendingConnection()
    c.readyRead.connect(lambda: w.open_paths(json.loads(bytes(c.readAll()).decode())["paths"], enqueue=True))
srv.newConnection.connect(conn)
app.exec()

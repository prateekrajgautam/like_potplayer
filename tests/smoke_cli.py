"""Real command-line single-instance test: first process runs the player, second sends --enqueue / --reload."""
import os, subprocess, sys, tempfile, threading, time
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
media = sys.argv[1]
env = dict(os.environ, LIKE_POTPLAYER_CONFIG=tempfile.mkdtemp())
from like_potplayer import cli

def second():
    time.sleep(5)
    r1 = subprocess.run([sys.executable, "-m", "like_potplayer", "--enqueue", media], env=env, cwd=root, timeout=30)
    r2 = subprocess.run([sys.executable, "-m", "like_potplayer", "--reload"], env=env, cwd=root, timeout=30)
    time.sleep(1.5)
    w = cli.LAST_PLAYER
    print(f"second instance exit codes: {r1.returncode} {r2.returncode}; playlist items: {len(w.items)}")
    sys.stdout.flush(); os._exit(0)

threading.Thread(target=second, daemon=True).start()
os.environ.update(env)
sys.exit(cli.main([media, "--slim"]))

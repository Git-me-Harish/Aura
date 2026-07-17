"""Detached backend launcher — spawns uvicorn in its own session."""
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "aura-backend"
LOG = BACKEND_DIR / "logs" / "uvicorn.log"
PIDFILE = BACKEND_DIR / "logs" / "uvicorn.pid"

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

LOG.parent.mkdir(parents=True, exist_ok=True)
PIDFILE.parent.mkdir(parents=True, exist_ok=True)

python_cmd = None
for candidate in [
    BACKEND_DIR / ".venv" / "Scripts" / "python.exe",
    BACKEND_DIR / ".venv" / "Scripts" / "python",
    BACKEND_DIR / ".venv" / "bin" / "python",
    PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
    PROJECT_ROOT / ".venv" / "bin" / "python",
    Path(sys.executable),
]:
    if candidate.exists():
        python_cmd = str(candidate)
        break

if python_cmd is None:
    raise SystemExit("Python interpreter not found")

with open(LOG, "wb") as logf:
    proc = subprocess.Popen(
        [python_cmd, "-m", "uvicorn",
         "app.main:app", "--host", "0.0.0.0", "--port", "8000",
         "--log-level", "info"],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # fully detach — own process group
    )

with open(PIDFILE, "w", encoding="utf-8") as f:
    f.write(str(proc.pid))

print(f"Launched uvicorn PID={proc.pid}, waiting for boot...")
for i in range(30):
    time.sleep(1)
    if proc.poll() is not None:
        print(f"Process exited early with code {proc.returncode}")
        with open(LOG, "rb") as lf:
            print("--- LOG ---")
            print(lf.read().decode(errors="replace"))
        sys.exit(1)
    # Check if port is listening
    import socket
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 8000))
        s.close()
        print(f"Port 8000 listening after {i+1}s — backend is up")
        sys.exit(0)
    except Exception:
        pass

print("Timeout — backend did not bind to :8000 within 30s")
sys.exit(2)

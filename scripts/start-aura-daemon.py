#!/usr/bin/env python3
"""Start AURA backend as a fully detached daemon."""
import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "aura-backend"
LOG_FILE = BACKEND_DIR / "logs" / "aura-backend.log"
PID_FILE = BACKEND_DIR / "logs" / "aura-backend.pid"

def start():
    # Check if already running
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if Path(PID_FILE).exists():
        try:
            old_pid = int(Path(PID_FILE).read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)  # Check if process exists
            print(f"AURA backend already running (pid={old_pid})")
            return
        except (ProcessLookupError, ValueError):
            Path(PID_FILE).unlink(missing_ok=True)

    # Double-fork daemonization
    pid = os.fork()
    if pid > 0:
        # Parent: wait briefly then exit
        import time
        time.sleep(2)
        if Path(PID_FILE).exists():
            new_pid = Path(PID_FILE).read_text(encoding="utf-8").strip()
            print(f"AURA backend started (pid={new_pid})")
        else:
            print("AURA backend may have failed to start")
        return

    # Decouple from parent environment
    os.setsid()
    os.umask(0)

    # Second fork
    pid = os.fork()
    if pid > 0:
        os._exit(0)

    # Write PID
    Path(PID_FILE).write_text(str(os.getpid()), encoding="utf-8")

    # Redirect stdin/stdout/stderr
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "rb") as f:
        os.dup2(f.fileno(), 0)
    with open(LOG_FILE, "ab") as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)

    # Now exec uvicorn
    os.chdir(BACKEND_DIR)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    uvicorn_cmd = None
    for candidate in [
        BACKEND_DIR / ".venv" / "Scripts" / "uvicorn.exe",
        BACKEND_DIR / ".venv" / "Scripts" / "uvicorn",
        BACKEND_DIR / ".venv" / "bin" / "uvicorn",
        PROJECT_ROOT / ".venv" / "Scripts" / "uvicorn.exe",
        PROJECT_ROOT / ".venv" / "bin" / "uvicorn",
        Path(sys.executable).parent / "uvicorn.exe",
        Path(sys.executable).parent / "uvicorn",
    ]:
        if candidate.exists():
            uvicorn_cmd = str(candidate)
            break

    if uvicorn_cmd is None:
        raise SystemExit("uvicorn executable not found")

    os.execvpe(
        uvicorn_cmd,
        [
            "uvicorn",
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
        ],
        env,
    )

if __name__ == "__main__":
    start()

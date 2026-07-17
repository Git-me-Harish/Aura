#!/usr/bin/env python3
"""Detached Next.js dev launcher — keeps the dev server alive across shell exits."""
import os
import socket
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NEXT_DIR = PROJECT_ROOT
LOG_PATH = os.path.join(PROJECT_ROOT, "aura-backend", "logs", "nextjs.log")
PID_PATH = os.path.join(PROJECT_ROOT, "aura-backend", "logs", "nextjs.pid")


def port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def main() -> None:
    if port_open(3000):
        print("Next.js already running on :3000")
        return

    env = os.environ.copy()
    env["NODE_OPTIONS"] = "--max-old-space-size=2048"

    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log = open(LOG_PATH, "ab", buffering=0)
    proc = subprocess.Popen(
        ["node_modules/.bin/next", "dev", "-p", "3000"],
        cwd=NEXT_DIR,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    with open(PID_PATH, "w") as f:
        f.write(str(proc.pid))

    print(f"Launched next dev PID={proc.pid}, waiting for boot...")
    for i in range(40):
        time.sleep(1.0)
        if port_open(3000):
            print(f"Port 3000 listening after {i+1}s — Next.js is up")
            return
        if proc.poll() is not None:
            print(f"Next.js exited early with code {proc.returncode}")
            sys.exit(1)
    print("Next.js did not bind :3000 in 40s")
    sys.exit(1)


if __name__ == "__main__":
    main()

"""
VERIDIQ local deployment — start backend + frontend with port conflict resolution.
Usage: python scripts/deploy_local.py
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_PORT = int(os.getenv("VERIDIQ_BACKEND_PORT", "8001"))
FRONTEND_PORT = int(os.getenv("VERIDIQ_FRONTEND_PORT", "5173"))


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def wait_http(url: str, timeout: float = 45.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.6)
    return False


def free_port(port: int) -> None:
    if port_free(port):
        return
    if sys.platform.startswith("win"):
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            pids = set()
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pids.add(parts[-1])
            for pid in pids:
                if pid.isdigit() and pid != "0":
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
        except Exception:
            pass
    time.sleep(1.0)


def main() -> int:
    env = os.environ.copy()
    env.setdefault("VERIDIQ_JWT_SECRET", "veridiq-local-dev-secret")
    env.setdefault("VERIDIQ_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000")

    free_port(BACKEND_PORT)
    free_port(FRONTEND_PORT)

    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", str(BACKEND_PORT)],
        cwd=str(ROOT),
        env=env,
    )
    frontend = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(FRONTEND_PORT)],
        cwd=str(ROOT / "frontend"),
        env=env,
        shell=sys.platform.startswith("win"),
    )

    be_ok = wait_http(f"http://127.0.0.1:{BACKEND_PORT}/api/v1/health")
    fe_ok = wait_http(f"http://127.0.0.1:{FRONTEND_PORT}/")

    print("=" * 60)
    print("VERIDIQ LOCAL DEPLOYMENT")
    print(f"Backend:  http://localhost:{BACKEND_PORT}  {'OK' if be_ok else 'FAIL'}")
    print(f"Docs:     http://localhost:{BACKEND_PORT}/docs")
    print(f"Frontend: http://localhost:{FRONTEND_PORT}  {'OK' if fe_ok else 'FAIL'}")
    print("=" * 60)

    if not be_ok or not fe_ok:
        backend.terminate()
        frontend.terminate()
        return 1

    print("Services running. Press Ctrl+C to stop.")
    try:
        while True:
            if backend.poll() is not None or frontend.poll() is not None:
                print("A service exited unexpectedly.")
                return 1
            time.sleep(2)
    except KeyboardInterrupt:
        backend.terminate()
        frontend.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

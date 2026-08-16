from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def start_api() -> subprocess.Popen[str] | None:
    if port_is_open("127.0.0.1", 8000):
        print("API already running on http://127.0.0.1:8000")
        return None

    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "agentmesh.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    return subprocess.Popen(cmd, cwd=str(project_root), env=env, text=True)


def start_streamlit() -> subprocess.Popen[str] | None:
    if port_is_open("127.0.0.1", 8501):
        print("Streamlit UI already running on http://127.0.0.1:8501")
        return None

    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    app_path = project_root / "src" / "agentmesh" / "ui" / "streamlit_app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.headless",
        "true",
        "--server.port",
        "8501",
    ]
    return subprocess.Popen(cmd, cwd=str(project_root), env=env, text=True)


def main() -> None:
    api_process = start_api()
    time.sleep(2)
    ui_process = start_streamlit()
    print("AgentMesh API: http://127.0.0.1:8000/health")
    print("AgentMesh UI: http://127.0.0.1:8501")
    try:
        if ui_process is not None:
            ui_process.wait()
        else:
            while True:
                time.sleep(5)
    finally:
        if api_process is not None:
            api_process.terminate()
        if ui_process is not None:
            ui_process.terminate()


if __name__ == "__main__":
    main()

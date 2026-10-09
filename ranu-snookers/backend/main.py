"""Start the backend for local development:  python main.py

Uses the project's venv automatically, applies local-dev overrides on top of .env
(real environment variables still win), and runs uvicorn with auto-reload on port 8000.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV_PYTHON = HERE / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

# Re-launch with the venv's Python if started with a different interpreter.
if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    sys.exit(subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]))

os.chdir(HERE)  # .env and alembic paths are relative to this folder

# Local-dev overrides (.env is configured for production).
os.environ.setdefault("COOKIE_SECURE", "false")    # allow login over plain http
os.environ.setdefault("REDIS_URL", "")             # no Redis server locally
os.environ.setdefault("RUN_EMBEDDED_WORKER", "true")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

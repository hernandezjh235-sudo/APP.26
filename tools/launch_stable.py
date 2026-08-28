#!/usr/bin/env python3
from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app.py"
RUNTIME = ROOT / "runtime_app.py"

# Keep the pushed app.py as the canonical source. The legacy V1.10.3 bootstrap
# patcher targets app.py by name, so apply it only to a temporary runtime copy
# and restore the pushed source immediately afterward.
source_bytes = SOURCE.read_bytes()
RUNTIME.write_bytes(source_bytes)

try:
    SOURCE.write_bytes(RUNTIME.read_bytes())
    subprocess.run([sys.executable, str(ROOT / "bootstrap_v1103.py")], cwd=str(ROOT), check=True)
    shutil.copy2(SOURCE, RUNTIME)
finally:
    SOURCE.write_bytes(source_bytes)

PATCHES = [
    "tools/apply_unefeated_opponent_k_pipeline_cleanup_v1.py",
    "tools/apply_manual_refresh_state_v2.py",
]
for rel in PATCHES:
    script = ROOT / rel
    if not script.exists():
        raise FileNotFoundError(f"Required runtime patch missing: {rel}")
    subprocess.run(
        [sys.executable, str(script), "--app", str(RUNTIME)],
        cwd=str(ROOT),
        check=True,
    )

py_compile.compile(str(RUNTIME), doraise=True)

# Production Streamlit must not watch files or auto-run when cache/data files
# change. Network/Savant work is now tied to the explicit board refresh action.
os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
os.environ.setdefault("STREAMLIT_SERVER_RUN_ON_SAVE", "false")
port = str(os.environ.get("PORT") or "8501")

cmd = [
    "streamlit", "run", str(RUNTIME),
    "--server.port", port,
    "--server.address", "0.0.0.0",
    "--server.headless", "true",
    "--server.fileWatcherType", "none",
    "--server.runOnSave", "false",
]
os.execvp(cmd[0], cmd)

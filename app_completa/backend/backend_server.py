#!/usr/bin/env python3
"""
Standalone backend server entry point for PyInstaller bundling.
"""
import os
import os
import sys
import warnings

# Silence FutureWarning from google.api_core about Python 3.9 support
# The system python on macOS is often 3.9, and we want to avoid noisy logs
warnings.filterwarnings("ignore", ".*You are using a non-supported Python version.*", category=FutureWarning)

# Monkeypatch importlib.metadata for Python < 3.10
if sys.version_info < (3, 10):
    try:
        import importlib.metadata
        import importlib_metadata
        if not hasattr(importlib.metadata, "packages_distributions"):
            importlib.metadata.packages_distributions = importlib_metadata.packages_distributions
    except ImportError:
        pass

# Fix "NameError: name 'help' is not defined" in bundled Gurobi
import builtins
if not hasattr(builtins, "help"):
    builtins.help = lambda *args, **kwargs: print("Help not available in frozen app")

# Set environment variables before importing anything else
os.environ.setdefault("CONCILIACION_BASE_PATH", os.path.expanduser("~/Documents/conciliacion"))
base_path = os.environ["CONCILIACION_BASE_PATH"]

os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(base_path, "clave_API_cloud_vision.json")
)

# Ensure data and database are stored in writable user directory
data_dir = os.path.join(base_path, "data")
os.makedirs(data_dir, exist_ok=True)

os.environ.setdefault("UPLOAD_DIR", os.path.join(data_dir, "uploads"))
os.environ.setdefault("REPORTS_DIR", os.path.join(data_dir, "reports"))
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{os.path.join(data_dir, 'reconciliation.db')}")

import uvicorn
from app.main_desktop import app
import gurobipy  # Force PyInstaller detection

if __name__ == "__main__":
    import threading
    import time
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000, help="Port to run the server on")
    args = parser.parse_args()

    def parent_watchdog(parent_pid):
        """
        Polls the parent process ID. If it changes (re-parented to init/launchd),
        it means the main app has died. We should exit immediately to avoid zombies.
        """
        while True:
            try:
                # Check if parent is still the same
                if os.getppid() != parent_pid:
                    print(f"Parent process {parent_pid} died. Exiting watchdog...")
                    os._exit(0) # Force exit
                time.sleep(1)
            except Exception:
                os._exit(0)

    # Start watchdog thread
    original_parent = os.getppid()
    print(f"Starting backend on port {args.port}. Parent PID: {original_parent}")
    
    watchdog = threading.Thread(target=parent_watchdog, args=(original_parent,), daemon=True)
    watchdog.start()

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")

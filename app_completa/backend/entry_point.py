import sys
import os
import uvicorn

# Ensure the backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now we can import the app as a module
# This allows relative imports inside app.main_desktop to resolve correctly
from app.main_desktop import app

if __name__ == "__main__":
    # Run the server
    # NOTE: Host must be 127.0.0.1 for the Tauri sidecar connection
    # Port 8000 is what the frontend expects
    uvicorn.run(app, host="127.0.0.1", port=8000)

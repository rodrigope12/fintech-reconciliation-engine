
import os
from pathlib import Path
from typing import Dict, Any

def update_env_file(updates: Dict[str, Any], env_path: str = ".env") -> bool:
    """
    Update values in the .env file.
    Creates the file if it doesn't exist.
    """
    try:
        # Define base path consistent with config.py
        base_path = Path(os.environ.get(
            "CONCILIACION_BASE_PATH",
            os.environ.get("APP_BASE_PATH", Path.home() / "Documents" / "conciliacion")
        ))

        # Resolve absolute path
        if not os.path.isabs(env_path):
            env_file = base_path / env_path
        else:
            env_file = Path(env_path)
            
        # Ensure parent directory exists
        env_file.parent.mkdir(parents=True, exist_ok=True)

        # Read existing lines
        lines = []
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # Map keys to line numbers for existing vars
        key_map = {}
        for idx, line in enumerate(lines):
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0].strip()
                key_map[key] = idx

        # Update or Append
        for key, value in updates.items():
            if value is None:
                continue
            
            # Format value
            str_val = str(value)
            
            new_line = f"{key}={str_val}\n"
            
            if key in key_map:
                lines[key_map[key]] = new_line
            else:
                # Append to end
                if lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"
                lines.append(new_line)

        # Write back
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(lines)
            
        return True
    except Exception as e:
        print(f"Error updating .env: {e}")
        return False

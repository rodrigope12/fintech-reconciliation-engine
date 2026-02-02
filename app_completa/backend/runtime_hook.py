
import os
import sys
import stat
from pathlib import Path

def setup_pulp_permissions():
    """
    Ensure PuLP solver binaries have execution permissions in the PyInstaller bundle.
    """
    if not hasattr(sys, '_MEIPASS'):
        return

    base_path = Path(sys._MEIPASS)
    # Based on where collect_data_files puts them. usually direct mapping or under pulp package.
    # verify_model_load confirms they are likely in pulp/solverdir or similar
    
    # We will look for 'pulp' directory in the temp path
    pulp_path = base_path / 'pulp'
    
    if not pulp_path.exists():
        # Sometimes it might be directly directly in 'solverdir' depending on how it was collected
        pulp_path = base_path / 'solverdir'

    if not pulp_path.exists():
        print("RuntimeHook: Pulp directory not found for permission fix.")
        return

    print(f"RuntimeHook: Fixing permissions recursively in {pulp_path}")
    
    # Recursive chmod for everything in solverdir
    for root, dirs, files in os.walk(pulp_path):
        for file in files:
            full_path = Path(root) / file
            try:
                # Add executable permission for user, group, other
                st = os.stat(full_path)
                os.chmod(full_path, st.st_mode | 0o111) # +x
                # print(f"RuntimeHook: +x {file}") 
            except Exception as e:
                print(f"RuntimeHook: Failed to chmod {file}: {e}")

setup_pulp_permissions()

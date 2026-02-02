# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_all

block_cipher = None

# Collect all gurobipy modules (binaries, datas, hiddenimports) to fix ModuleNotFoundError
gurobi_datas, gurobi_binaries, gurobi_hiddenimports = collect_all('gurobipy')

a = Analysis(
    ['backend_server.py'],
    pathex=[],
    binaries=gurobi_binaries,
    datas=[('data', 'data'), ('../gurobi.lic', '.')] + collect_data_files('pulp') + gurobi_datas,
    hiddenimports=[
        'uvicorn',
        'gurobipy',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'pulp',
        'pulp.solverdir',
        'google.cloud.vision',
        'sklearn.utils._typedefs',
        'sklearn.neighbors._partition_nodes',
    ] + gurobi_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='conciliacion-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for trade_dashboard_app native Windows desktop build.

Packages the Streamlit Command Center with Microsoft Edge Chromium WebView2
(via pywebview) into a standalone native Windows desktop application.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Base workspace paths
WORKSPACE_ROOT = Path(SPECPATH).resolve().parent
SRC_DIR = WORKSPACE_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

# Collect all Streamlit static web assets, frontend bundles, and templates
datas = []
datas += collect_data_files("streamlit")
datas += collect_data_files("trade_dashboard_app")

# Add app.py explicitly so it can be located in frozen bundle
app_py_path = SRC_DIR / "trade_dashboard_app" / "app.py"
if app_py_path.exists():
    datas.append((str(app_py_path), "trade_dashboard_app"))

# Collect all hidden submodules required by the runtime engines
hiddenimports = []
hiddenimports += collect_submodules("streamlit")
hiddenimports += collect_submodules("trade_dashboard_app")
hiddenimports += collect_submodules("trade_data_options")
hiddenimports += collect_submodules("trade_paper")
hiddenimports += collect_submodules("trade_agents")
hiddenimports += collect_submodules("trade_hedge")
hiddenimports += collect_submodules("trade_macro")
hiddenimports += collect_submodules("trade_risk_premium")
hiddenimports += [
    "webview",
    "clr",
    "clr_loader",
    "pythonnet",
    "websockets",
    "websockets.asyncio",
    "websockets.asyncio.client",
    "altair",
    "pandas",
    "pyarrow",
    "pydeck",
]

block_cipher = None

a = Analysis(
    [str(SRC_DIR / "trade_dashboard_app" / "desktop.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6", "tkinter", "matplotlib.tests", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Single-directory onedir distribution (fastest startup, recommended for WebView2 + Streamlit)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TradeDashboardApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Set to True for developer telemetry and stderr/stdout logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TradeDashboardApp",
)

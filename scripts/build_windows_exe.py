"""Build script for compiling trade_dashboard_app into a native Windows executable.

Usage:
    python scripts/build_windows_exe.py [--skip-tests] [--clean]

Prerequisites:
    pip install pyinstaller pywebview streamlit pythonnet
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = WORKSPACE_ROOT / "packaging" / "trade_dashboard_app.spec"
DIST_DIR = WORKSPACE_ROOT / "dist"
BUILD_DIR = WORKSPACE_ROOT / "build"
EXE_TARGET = DIST_DIR / "TradeDashboardApp" / "TradeDashboardApp.exe"


def check_prerequisites() -> None:
    """Verifies build dependencies are installed and available."""
    print("Checking build prerequisites...")
    required = ["PyInstaller", "webview", "streamlit"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"Error: Missing required packaging packages: {', '.join(missing)}")
        print(f"Run: pip install {' '.join(missing)}")
        sys.exit(1)
    print("All packaging prerequisites satisfied.")


def run_tests() -> None:
    """Runs test suite to guard against packaging broken code."""
    print("Running verification test suite before packaging...")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_dashboard_app.py",
        "tests/test_data_options_streaming.py",
        "-q",
    ]
    res = subprocess.run(cmd, cwd=WORKSPACE_ROOT)
    if res.returncode != 0:
        print("Error: Test suite failed! Halting packaging.")
        sys.exit(res.returncode)
    print("Verification tests passed cleanly.")


def build_executable(clean: bool = False) -> None:
    """Executes PyInstaller with the spec file."""
    if not SPEC_FILE.exists():
        print(f"Error: Spec file not found at {SPEC_FILE}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
    ]
    if clean:
        cmd.append("--clean")

    print(f"Executing: {' '.join(cmd)}")
    start = time.time()
    res = subprocess.run(cmd, cwd=WORKSPACE_ROOT)
    elapsed = time.time() - start

    if res.returncode != 0:
        print(f"PyInstaller build failed with exit code {res.returncode}")
        sys.exit(res.returncode)

    if EXE_TARGET.exists():
        size_mb = EXE_TARGET.stat().st_size / (1024 * 1024)
        print("============================================================")
        print("SUCCESS: Native Windows Executable Built Successfully!")
        print(f"Executable: {EXE_TARGET}")
        print(f"File Size:  {size_mb:.2f} MB")
        print(f"Build Time: {elapsed:.1f} seconds")
        print("============================================================")
        print("To launch the native desktop application:")
        print(f"  & '{EXE_TARGET}'")
        print("============================================================")
    else:
        print(f"Warning: Executable not found at expected path: {EXE_TARGET}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile Trade Dashboard to Windows EXE")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pre-build test validation")
    parser.add_argument("--clean", action="store_true", help="Clean PyInstaller cache and build dirs before building")
    args = parser.parse_args()

    check_prerequisites()
    if not args.skip_tests:
        run_tests()
    build_executable(clean=args.clean)


if __name__ == "__main__":
    main()

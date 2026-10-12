"""Moomoo OpenD Automated Downloader, Setup, and Launcher for Windows.

Automates:
1. Fetching official Moomoo OpenD Windows package (v10.11.7108).
2. Extracting into tools/moomoo_opend/.
3. Verifying and configuring OpenD.xml (127.0.0.1:11111).
4. Launching OpenD gateway in visualization (GUI) or daemon mode.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("moomoo_opend_setup")

OPEND_DOWNLOAD_URL = "https://softwaredownload.futustatic.com/moomoo_OpenD_10.11.7108_Windows.7z"
DEFAULT_TARGET_DIR = Path("c:/Agentic AI Algorithmic Trading System Software/tools/moomoo_opend")


def is_port_in_use(host: str = "127.0.0.1", port: int = 11111) -> bool:
    """Check if OpenD socket port is already listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def download_opend(target_dir: Path) -> Path:
    """Download OpenD 7z archive if not already downloaded."""
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / "moomoo_OpenD_10.11.7108_Windows.7z"

    if archive_path.exists() and archive_path.stat().st_size > 200_000_000:
        logger.info("OpenD archive already downloaded at %s (%d MB)", archive_path, archive_path.stat().st_size // (1024 * 1024))
        return archive_path

    logger.info("Downloading Moomoo OpenD from %s (~238 MB)...", OPEND_DOWNLOAD_URL)
    req = urllib.request.Request(
        OPEND_DOWNLOAD_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )

    start_time = time.time()
    with urllib.request.urlopen(req) as resp, open(archive_path, "wb") as out_f:
        total_size = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks

        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out_f.write(chunk)
            downloaded += len(chunk)
            pct = (downloaded / total_size * 100) if total_size else 0
            if downloaded % (10 * 1024 * 1024) < chunk_size:
                logger.info("Downloaded %d MB / %d MB (%.1f%%)", downloaded // (1024 * 1024), total_size // (1024 * 1024), pct)

    elapsed = time.time() - start_time
    logger.info("Download completed in %.1fs: %s (%d MB)", elapsed, archive_path, archive_path.stat().st_size // (1024 * 1024))
    return archive_path


def extract_opend(archive_path: Path, target_dir: Path) -> Path:
    """Extract OpenD 7z archive using py7zr or tar.exe."""
    # Check if already extracted
    for exe_name in ["FutuOpenD.exe", "OpenD.exe", "moomoo_OpenD.exe"]:
        matches = list(target_dir.rglob(exe_name))
        if matches:
            logger.info("OpenD already extracted at %s", matches[0])
            return matches[0]

    logger.info("Extracting %s to %s...", archive_path, target_dir)
    try:
        import py7zr
        with py7zr.SevenZipFile(archive_path, mode="r") as z:
            z.extractall(path=target_dir)
        logger.info("Extraction via py7zr successful.")
    except Exception as exc:
        logger.warning("py7zr extraction failed (%s), attempting tar.exe fallback...", exc)
        res = subprocess.run(["tar.exe", "-xf", str(archive_path), "-C", str(target_dir)], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"tar.exe extraction failed: {res.stderr}")
        logger.info("Extraction via tar.exe successful.")

    for exe_name in ["FutuOpenD.exe", "OpenD.exe", "moomoo_OpenD.exe"]:
        matches = list(target_dir.rglob(exe_name))
        if matches:
            logger.info("Found OpenD executable at %s", matches[0])
            return matches[0]

    raise FileNotFoundError(f"Could not find OpenD executable in {target_dir}")


def configure_opend_xml(opend_exe: Path, port: int = 11111) -> Path:
    """Ensure OpenD.xml exists and has port 11111 configured."""
    xml_path = opend_exe.parent / "OpenD.xml"
    if not xml_path.exists():
        xml_template = opend_exe.parent / "OpenD_Template.xml"
        if xml_template.exists():
            shutil.copy(xml_template, xml_path)
            logger.info("Copied OpenD_Template.xml to %s", xml_path)

    if xml_path.exists():
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            # Find or update port and ip
            ip_elem = root.find(".//ip")
            if ip_elem is not None:
                ip_elem.text = "127.0.0.1"
            port_elem = root.find(".//port")
            if port_elem is not None:
                port_elem.text = str(port)
            tree.write(xml_path)
            logger.info("Updated %s: ip=127.0.0.1, port=%d", xml_path, port)
        except Exception as exc:
            logger.warning("Failed to parse OpenD.xml (%s), leaving as is", exc)

    return xml_path


def launch_opend(opend_exe: Path, is_daemon: bool = True) -> subprocess.Popen:
    """Launch OpenD gateway process."""
    if is_port_in_use("127.0.0.1", 11111):
        logger.info("OpenD port 11111 is ALREADY listening. Gateway is running!")
        return None

    logger.info("Launching OpenD gateway from %s ...", opend_exe)
    cmd = [str(opend_exe)]

    if is_daemon:
        proc = subprocess.Popen(
            cmd,
            cwd=str(opend_exe.parent),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        )
    else:
        proc = subprocess.Popen(cmd, cwd=str(opend_exe.parent))

    logger.info("OpenD process started (PID: %d). Waiting for port 11111...", proc.pid)
    for _ in range(15):
        time.sleep(1)
        if is_port_in_use("127.0.0.1", 11111):
            logger.info("Success! OpenD is listening on 127.0.0.1:11111.")
            return proc

    logger.warning("OpenD launched but port 11111 not yet open. (May be waiting for user login in GUI).")
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description="Moomoo OpenD Downloader & Setup")
    parser.add_argument("--dir", default=str(DEFAULT_TARGET_DIR), help="Target directory for OpenD")
    parser.add_argument("--launch", action="store_true", help="Launch OpenD after setup")
    parser.add_argument("--gui", action="store_true", help="Launch OpenD in GUI window instead of detached")
    parser.add_argument("--check", action="store_true", help="Check if OpenD port 11111 is running")
    args = parser.parse_args()

    if args.check:
        in_use = is_port_in_use("127.0.0.1", 11111)
        if in_use:
            logger.info("OpenD socket 127.0.0.1:11111 is ONLINE.")
            sys.exit(0)
        else:
            logger.warning("OpenD socket 127.0.0.1:11111 is OFFLINE.")
            sys.exit(1)

    target_dir = Path(args.dir)
    archive = download_opend(target_dir)
    exe = extract_opend(archive, target_dir)
    configure_opend_xml(exe, 11111)

    if args.launch:
        launch_opend(exe, is_daemon=not args.gui)


if __name__ == "__main__":
    main()

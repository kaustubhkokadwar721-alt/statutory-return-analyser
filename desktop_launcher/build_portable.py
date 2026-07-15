"""Build the private, portable Windows distribution from the browser app."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "gstr_web"
LAUNCHER = ROOT / "desktop_launcher" / "launcher.py"
BUILD = ROOT / "desktop_launcher" / "build"
RELEASE = ROOT / "release" / "StatutoryReturnAnalyser"
ARCHIVE = ROOT / "release" / "StatutoryReturnAnalyser-portable.zip"
APP_FILES = ("index.html", "app.js", "sw.js", "engine.zip")
APP_DIRECTORIES = ("themes", "fonts", "ocr", "pyodide", "wheels")


def reset(path: Path) -> None:
    path.resolve().relative_to(ROOT)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_app() -> None:
    app = RELEASE / "gstr_web"
    app.mkdir()
    for name in APP_FILES:
        shutil.copy2(SOURCE / name, app / name)
    for name in APP_DIRECTORIES:
        shutil.copytree(SOURCE / name, app / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def make_zip() -> None:
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in RELEASE.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(RELEASE.parent))


def main() -> None:
    reset(BUILD)
    reset(RELEASE)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        ARCHIVE.resolve().relative_to(ROOT)
        ARCHIVE.unlink()

    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "StatutoryReturnLauncher", "--distpath", str(BUILD / "dist"),
        "--workpath", str(BUILD / "work"), "--specpath", str(BUILD / "spec"), str(LAUNCHER),
    ], check=True)
    shutil.copy2(BUILD / "dist" / "StatutoryReturnLauncher.exe", RELEASE / "StatutoryReturnLauncher.exe")
    copy_app()
    make_zip()
    print(f"Portable folder: {RELEASE}")
    print(f"Portable ZIP:    {ARCHIVE}")


if __name__ == "__main__":
    main()

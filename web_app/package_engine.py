"""Build and verify the browser engine archive from its canonical source tree."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "engine"
ARCHIVE = ROOT / "engine.zip"


def source_files():
    return sorted(path for path in SOURCE.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify() -> bool:
    expected = {path.relative_to(SOURCE).as_posix(): digest(path.read_bytes()) for path in source_files()}
    if not ARCHIVE.exists():
        print("engine.zip is missing")
        return False
    with ZipFile(ARCHIVE) as archive:
        actual = {
            name: digest(archive.read(name))
            for name in archive.namelist()
            if not name.endswith("/") and "__pycache__/" not in name and not name.endswith(".pyc")
        }
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(name for name in set(expected) & set(actual) if expected[name] != actual[name])
    for label, entries in (("missing", missing), ("extra", extra), ("changed", changed)):
        if entries:
            print(f"{label}: {', '.join(entries)}")
    return not (missing or extra or changed)


def build() -> None:
    with ZipFile(ARCHIVE, "w", ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, path.relative_to(SOURCE).as_posix())
    if not verify():
        raise SystemExit("engine.zip verification failed")
    print(f"Built {ARCHIVE.name} from {len(source_files())} files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="check engine.zip without rebuilding it")
    args = parser.parse_args()
    if args.verify:
        raise SystemExit(0 if verify() else 1)
    build()

"""Vendor and verify the pinned browser OCR runtime. Run from gstr_web/."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEST = ROOT / "ocr"
SOURCES = {
    "tesseract": "https://registry.npmjs.org/tesseract.js/-/tesseract.js-5.1.1.tgz",
    "core": "https://registry.npmjs.org/tesseract.js-core/-/tesseract.js-core-5.1.1.tgz",
    "pdfjs": "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-4.10.38.tgz",
    "english": "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/eng.traineddata",
}
HASHES = {
    "pdf.min.mjs": "27fc2a057a00f92a4334ad06e17dbd7259912954e9fb7f76400bcca5fd190a9c",
    "pdf.worker.min.mjs": "1baa1844c89c80a5b2797c916e75ab29254be46d8e9cb53cb6364d7aad84be36",
    "tesseract.min.js": "a8e29918d098b2b06e1012bdaeffb4aec0445c5d5654709023e0bd1f442a80e8",
    "worker.min.js": "aca1229639fc9907d86f96e825955a2b7c5716d17f3bc3acd71f9c7ab66181fc",
    "core/tesseract-core-lstm.wasm.js": "8f04aa0cc81e7bde33f80e92fa01a7a665f0b4884d098acf5de9c7104a11dfaa",
    "core/tesseract-core-simd-lstm.wasm.js": "ce20eda9533cbed1e6c2b4276fbae1e0adc61b6754b5513084be601787b457cf",
    "core/tesseract-core-simd.wasm.js": "63f232c4f7a97b04e52eb940202700b2c6239783a75d0ff0553274fac530cd5c",
    "core/tesseract-core.wasm.js": "2b8c8c92b8788807061fb4bb16c5acdf000c149e100255f879f78d2c58ca9969",
    "lang/eng.traineddata": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> bool:
    valid = True
    for relative, expected in HASHES.items():
        path = DEST / relative
        actual = _digest(path) if path.is_file() else "missing"
        if actual != expected:
            print(f"invalid: {relative}")
            valid = False
    return valid


def _download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url) as response, destination.open("wb") as target:
        shutil.copyfileobj(response, target)


def _extract_member(archive_path: Path, member: str, target: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        source = archive.extractfile(member)
        if source is None:
            raise FileNotFoundError(member)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            shutil.copyfileobj(source, output)


def build() -> None:
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        bundles = {}
        for name in ("tesseract", "core", "pdfjs"):
            bundles[name] = temp / f"{name}.tgz"
            _download(SOURCES[name], bundles[name])
        _extract_member(bundles["tesseract"], "package/dist/tesseract.min.js", DEST / "tesseract.min.js")
        _extract_member(bundles["tesseract"], "package/dist/worker.min.js", DEST / "worker.min.js")
        _extract_member(bundles["pdfjs"], "package/build/pdf.min.mjs", DEST / "pdf.min.mjs")
        _extract_member(bundles["pdfjs"], "package/build/pdf.worker.min.mjs", DEST / "pdf.worker.min.mjs")
        for name in ("tesseract-core-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js",
                     "tesseract-core-simd.wasm.js", "tesseract-core.wasm.js"):
            _extract_member(bundles["core"], f"package/{name}", DEST / "core" / name)
        (DEST / "lang").mkdir(parents=True, exist_ok=True)
        _download(SOURCES["english"], DEST / "lang" / "eng.traineddata")
    if not verify():
        raise SystemExit("OCR asset verification failed")
    print(f"Vendored {len(HASHES)} OCR assets.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify local OCR assets only")
    args = parser.parse_args()
    if args.verify:
        raise SystemExit(0 if verify() else 1)
    build()

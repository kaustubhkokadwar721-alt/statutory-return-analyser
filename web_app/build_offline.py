"""Vendor Pyodide runtime + all wheels locally so the app runs with ZERO network.
Run from web_app/ :  python build_offline.py
"""
import json, os, sys, subprocess, urllib.request

BASE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"
PYO = "pyodide"
WHEELS = "wheels"
os.makedirs(PYO, exist_ok=True)
os.makedirs(WHEELS, exist_ok=True)

def dl(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return
    urllib.request.urlretrieve(url, dest)
    print(f"  + {os.path.basename(dest):42} {os.path.getsize(dest)//1024:>7} KB")

# 1. Pyodide core runtime
print("[1] Pyodide core runtime")
for f in ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]:
    dl(BASE + f, os.path.join(PYO, f))

# 2. Dependency closure for the packages we loadPackage(), from the lock file
print("[2] Pyodide package wheels (dependency closure)")
lock = json.load(open(os.path.join(PYO, "pyodide-lock.json"), encoding="utf-8"))
pkgs = lock["packages"]
def norm(n): return n.lower().replace("_", "-")
index = {norm(k): k for k in pkgs}
seen = set()
def closure(name):
    k = index.get(norm(name))
    if not k or k in seen:
        return
    seen.add(k)
    for d in pkgs[k].get("depends", []):
        closure(d)
for w in ["micropip", "Pillow", "cryptography", "pandas"]:
    closure(w)
for k in sorted(seen):
    dl(BASE + pkgs[k]["file_name"], os.path.join(PYO, pkgs[k]["file_name"]))
print(f"    {len(seen)} pyodide packages vendored")

# 3. Pure-Python wheels from PyPI (micropip-installed at runtime)
print("[3] PyPI pure wheels")
reqs = [
    "pdfplumber==0.11.9", "pdfminer.six==20260107", "XlsxWriter==3.2.9",
    "charset-normalizer==3.4.7",
]
rc = subprocess.run(
    [sys.executable, "-m", "pip", "download",
     "--only-binary=:all:", "--no-deps",
     "--python-version", "3.12", "--implementation", "py", "--abi", "none", "--platform", "any",
     "-d", WHEELS, *reqs],
    capture_output=True, text=True)
print(rc.stdout[-1500:])
if rc.returncode != 0:
    print("PIP ERR:", rc.stderr[-1500:])
for f in sorted(os.listdir(WHEELS)):
    print(f"  + wheels/{f}")
print("\nDONE.")

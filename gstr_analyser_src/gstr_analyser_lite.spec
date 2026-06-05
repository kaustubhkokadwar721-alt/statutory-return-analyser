# gstr_analyser_lite.spec
# Build: cd gstr_analyser_src && pyinstaller gstr_analyser_lite.spec --noconfirm
# No Textual — Rich CLI only. Smaller exe.

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

pdfplumber_datas,  pdfplumber_binaries,  pdfplumber_hi  = collect_all("pdfplumber")
pdfminer_datas,    pdfminer_binaries,    pdfminer_hi    = collect_all("pdfminer")
pandas_datas,      pandas_binaries,      pandas_hi      = collect_all("pandas")
crypto_datas,      crypto_binaries,      crypto_hi      = collect_all("cryptography")

all_datas    = pdfplumber_datas + pdfminer_datas + pandas_datas + crypto_datas
all_binaries = pdfplumber_binaries + pdfminer_binaries + pandas_binaries + crypto_binaries

hidden_imports = [
    *pdfplumber_hi,
    *pdfminer_hi,
    *pandas_hi,
    *crypto_hi,
    # Pillow
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFilter",
    # xlsxwriter
    "xlsxwriter", "xlsxwriter.workbook", "xlsxwriter.worksheet",
    # numpy
    "numpy", "numpy.core._methods", "numpy.lib.format",
    # rich
    "rich", "rich.console", "rich.live", "rich.markup",
    "rich.panel", "rich.prompt", "rich.table", "rich.text",
    # tkinter folder picker
    *collect_submodules("tkinter"),
    # Windows
    "winreg", "ctypes", "ctypes.wintypes",
    # stdlib
    "pickle", "threading", "concurrent.futures", "logging",
]

a = Analysis(
    ["main_lite.py"],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Textual TUI — not used in lite version
        "textual",
        # Test / dev
        "pytest", "unittest", "tkinter.test",
        # Notebooks
        "IPython", "jupyter", "notebook", "zmq", "traitlets",
        # Plotting / scientific
        "matplotlib", "scipy",
        # JIT
        "numba", "llvmlite", "pyarrow",
        # Unused pandas I/O
        "openpyxl", "python_calamine", "lxml", "lxml.etree",
        "html5lib", "bs4", "tables", "h5py", "fastparquet", "sqlalchemy",
        # pywin32 COM
        "Pythonwin", "pywin32", "win32com", "pythoncom",
        "pywintypes", "win32", "win32api", "win32gui",
        # Unused
        "OpenSSL",
        "pandas.io.formats.style", "pandas.io.clipboard", "pandas.plotting",
        "jinja2", "pygments", "psutil", "setuptools", "pkg_resources",
    ],
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
    exclude_binaries=False,
    name="GSTR_Analyser_Lite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

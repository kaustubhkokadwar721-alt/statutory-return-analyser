# gstr_analyser.spec
# Build: cd gstr_analyser_src && pyinstaller gstr_analyser.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_submodules, collect_all

block_cipher = None

# --- collect_all pulls binaries + datas + hiddenimports in one call ---
pdfplumber_datas,    pdfplumber_binaries,    pdfplumber_hi    = collect_all("pdfplumber")
pdfminer_datas,      pdfminer_binaries,      pdfminer_hi      = collect_all("pdfminer")
pandas_datas,        pandas_binaries,        pandas_hi        = collect_all("pandas")
textual_datas,       textual_binaries,       textual_hi       = collect_all("textual")
# cryptography required by pdfminer.pdfdocument (unconditional top-level import)
crypto_datas,        crypto_binaries,        crypto_hi        = collect_all("cryptography")

all_datas    = pdfplumber_datas + pdfminer_datas + pandas_datas + textual_datas + crypto_datas
all_binaries = pdfplumber_binaries + pdfminer_binaries + pandas_binaries + textual_binaries + crypto_binaries

hidden_imports = [
    *pdfplumber_hi,
    *pdfminer_hi,
    *pandas_hi,
    *textual_hi,
    *crypto_hi,
    # Pillow — pdfplumber imports at PDF open time
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFilter",
    # xlsxwriter
    "xlsxwriter",
    "xlsxwriter.workbook",
    "xlsxwriter.worksheet",
    # numpy
    "numpy",
    "numpy.core._methods",
    "numpy.lib.format",
    # rich
    "rich",
    "rich.console",
    "rich.live",
    "rich.markup",
    "rich.panel",
    "rich.prompt",
    "rich.table",
    "rich.text",
    # tkinter — folder picker dialog
    *collect_submodules("tkinter"),
    # Windows-specific
    "winreg",
    "ctypes",
    "ctypes.wintypes",
    # stdlib
    "pickle",
    "threading",
    "concurrent.futures",
    "logging",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test / dev frameworks
        "pytest",
        "unittest",
        "tkinter.test",
        # Notebooks / interactive
        "IPython",
        "jupyter",
        "notebook",
        "zmq",
        "traitlets",
        # Plotting / scientific (unused)
        "matplotlib",
        "scipy",
        # JIT compiler chain (~178 MB) — pandas optional, never called
        "numba",
        "llvmlite",
        "pyarrow",
        # Optional pandas I/O backends (unused — only xlsxwriter used)
        "openpyxl",
        "python_calamine",
        "lxml",
        "lxml.etree",
        "lxml.objectify",
        "lxml.isoschematron",
        "html5lib",
        "bs4",
        "tables",
        "h5py",
        "fastparquet",
        "sqlalchemy",
        # pywin32 GUI / COM (unused)
        "Pythonwin",
        "pywin32",
        "win32com",
        "pythoncom",
        "pywintypes",
        "win32",
        "win32api",
        "win32gui",
        # Crypto — cryptography is REQUIRED by pdfminer.pdfdocument (unconditional import)
        # Do NOT exclude cryptography or cffi here
        "OpenSSL",
        # Pandas style/clipboard subsystems (unused)
        "pandas.io.formats.style",
        "pandas.io.clipboard",
        "pandas.plotting",
        "jinja2",
        # Misc
        "pygments",
        "psutil",
        "setuptools",
        "pkg_resources",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- onefile: binaries + datas packed into the exe itself ---
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # include binaries directly (onefile)
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,  # onefile mode — everything inside single exe
    name="GSTR_Analyser",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,            # Textual requires a visible console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # set to icon="icon.ico" once you place icon.ico here
)

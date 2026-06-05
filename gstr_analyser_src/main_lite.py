"""GSTR Return Analyser — Lite CLI.

Usage:
    python main_lite.py
    python main_lite.py --return-type gstr1  --input-dir <folder> --output-dir <folder>
    python main_lite.py --return-type gstr3b --input-dir <folder> --output-dir <folder>
"""

import argparse
import io
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from gstr_analyser.constants import APP_NAME, VERSION

console = Console()

_WORKFLOWS = {
    "1": ("gstr1",  "GSTR-1",  "GSTR1_Verified_Reports",
          ["GSTR1_Auditor_Master.xlsx",  "GSTR1_Analytics_Master.xlsx"]),
    "2": ("gstr3b", "GSTR-3B", "GSTR3B_Verified_Reports",
          ["GSTR3B_Auditor_Master.xlsx", "GSTR3B_Analytics_Master.xlsx"]),
}

_STEP_LABELS = [
    "Validate PDFs",
    "Extract tables",
    "Run sanity checks",
    "Build analytics",
    "Write workbooks",
]


# ── helpers ──────────────────────────────────────────────────────────────────

def _dpi_aware() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _pick_folder(title: str) -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.lift()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title=title)
        root.destroy()
        return folder if folder else None
    except Exception:
        return None


def _ask_folder(label: str, title: str, optional: bool = False) -> str | None:
    """GUI picker with typed-path fallback."""
    folder = _pick_folder(title)
    if folder:
        return folder
    hint = "paste path, or Enter to skip" if optional else "paste path"
    raw = Prompt.ask(f"  {label} ({hint})", default="").strip().strip('"').strip("'")
    if not raw:
        return None
    if os.path.isdir(raw):
        return raw
    console.print(f"  [red]Not found:[/] {raw}")
    return None


def _check_lock(output_dir: str, filenames: list) -> str | None:
    for name in filenames:
        path = os.path.join(output_dir, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "a+b"):
                pass
        except OSError:
            return name
    return None


def _dep_check() -> None:
    missing = []
    for pkg in ("pdfplumber", "pandas", "xlsxwriter", "rich"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        console.print(f"[red]Missing packages:[/] {', '.join(missing)}")
        console.print(f"[dim]pip install {' '.join(missing)}[/]")
        Prompt.ask("Press Enter to exit", default="")
        sys.exit(1)


# ── UI ───────────────────────────────────────────────────────────────────────

def _header() -> None:
    console.clear()
    console.print(f"\n  [bold white]{APP_NAME}[/]  [dim]v{VERSION}[/]")
    console.print(f"  [dim]{'─' * 38}[/]\n")


def _menu() -> None:
    console.print("  [bold #ffb703]1[/]  GSTR-1    Outward supplies · HSN · reconciliation")
    console.print("  [bold #ffb703]2[/]  GSTR-3B   Liability · ITC · payments · reverse charge")
    console.print("  [bold #ffb703]Q[/]  Quit\n")


# ── run ───────────────────────────────────────────────────────────────────────

def _run(key: str) -> None:
    wf_type, wf_name, out_subdir, lock_files = _WORKFLOWS[key]

    console.print(f"\n  [bold]{wf_name}[/] — select folders\n")

    input_dir = _ask_folder("Input folder", f"Select folder with {wf_name} PDFs")
    if not input_dir:
        console.print("  [yellow]No input folder. Returning to menu.[/]\n")
        return

    out_base = _ask_folder("Output folder", "Select output folder  (cancel = use input)", optional=True)
    if not out_base:
        out_base = input_dir

    output_dir = os.path.join(out_base, out_subdir)

    locked = _check_lock(output_dir, lock_files)
    if locked:
        console.print(f"\n  [red]File locked:[/] Close [bold]{locked}[/] in Excel, then retry.\n")
        return

    os.makedirs(output_dir, exist_ok=True)

    console.print(f"\n  [dim]Input :[/]  {input_dir}")
    console.print(f"  [dim]Output:[/]  {output_dir}\n")
    console.print(f"  Running {wf_name} ...\n")

    # progress callback — prints each completed step
    last_step = [-1]

    def _cb(step: int, detail: str) -> None:
        if step == 0 and last_step[0] < 0:
            last_step[0] = 0
            if detail:
                console.print(f"  [dim]{detail}[/]")
            return
        while last_step[0] < step and last_step[0] < len(_STEP_LABELS):
            idx = last_step[0]
            label = _STEP_LABELS[idx]
            suffix = f"  [dim]{detail}[/]" if (idx == step - 1 and detail) else ""
            console.print(f"  [green]✓[/] {label}{suffix}")
            last_step[0] += 1

    try:
        if wf_type == "gstr1":
            from gstr_analyser.gstr1.pipeline import run_pipeline_gstr1
            review, analytics = run_pipeline_gstr1(input_dir, output_dir, progress_cb=_cb)
        else:
            from gstr_analyser.gstr3b.pipeline import run_pipeline_gstr3b
            review, analytics = run_pipeline_gstr3b(input_dir, output_dir, progress_cb=_cb)
    except Exception as exc:
        console.print(f"\n  [bold red]Error:[/] {exc}\n")
        return

    # flush any remaining steps
    while last_step[0] < len(_STEP_LABELS):
        console.print(f"  [green]✓[/] {_STEP_LABELS[last_step[0]]}")
        last_step[0] += 1

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column(style="dim",   width=10)
    table.add_column(style="white", ratio=1)
    table.add_column(justify="right", style="#ffb703", width=8)
    table.add_row("Review",    review,    f"{os.path.getsize(review)    // 1024} KB")
    table.add_row("Analytics", analytics, f"{os.path.getsize(analytics) // 1024} KB")

    console.print()
    console.print(table)
    console.print("  [bold green]Done.[/]\n")


# ── headless mode ─────────────────────────────────────────────────────────────

def _headless(return_type: str, input_dir: str, output_dir: str) -> int:
    if not input_dir or not output_dir:
        print("ERROR: --input-dir and --output-dir required.", file=sys.stderr)
        return 1
    if not os.path.isdir(input_dir):
        print(f"ERROR: Input folder not found: {input_dir}", file=sys.stderr)
        return 1
    os.makedirs(output_dir, exist_ok=True)
    try:
        if return_type == "gstr1":
            from gstr_analyser.gstr1.pipeline import run_pipeline_gstr1
            review, analytics = run_pipeline_gstr1(input_dir, output_dir)
        else:
            from gstr_analyser.gstr3b.pipeline import run_pipeline_gstr3b
            review, analytics = run_pipeline_gstr3b(input_dir, output_dir)
    except Exception as exc:
        import traceback
        print(f"ERROR: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    print(f"Review:    {review}")
    print(f"Analytics: {analytics}")
    return 0


# ── entry ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="GSTR Return Analyser (Lite)")
    parser.add_argument("--return-type", choices=("gstr1", "gstr3b"))
    parser.add_argument("--input-dir")
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    if args.return_type:
        return _headless(args.return_type, args.input_dir, args.output_dir)

    _dpi_aware()
    _dep_check()

    while True:
        _header()
        _menu()
        choice = Prompt.ask("  Choice", choices=["1", "2", "Q", "q"])
        if choice.upper() == "Q":
            console.print("[dim]Bye.[/]\n")
            break
        _run(choice)
        Prompt.ask("  Press Enter to return to menu", default="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

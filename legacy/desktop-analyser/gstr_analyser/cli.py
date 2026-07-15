"""Command-line interface for the GSTR Return Analyser."""

import os
import sys

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .constants import APP_NAME, VERSION
from .utils import check_file_locks

console = Console()


try:
    import tkinter as tk
    from tkinter import filedialog

    _HAS_TKINTER = True
except ImportError:
    _HAS_TKINTER = False


def _set_dpi_awareness() -> None:
    """Make tkinter dialogs crisp on high-DPI Windows displays."""
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


def dependency_check() -> None:
    """Fail fast with a friendly message if any required package is missing."""
    required = [
        ("pdfplumber", "pdfplumber"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("xlsxwriter", "xlsxwriter"),
        ("rich", "rich"),
    ]
    missing = []
    for import_name, package_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(package_name)

    if not missing:
        return

    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold red", no_wrap=True)
    body.add_column(style="white")
    for package in missing:
        body.add_row("MISSING", package)
    body.add_row("FIX", f"pip install {' '.join(missing)}")
    console.print(Panel(body, title="Dependency Check Failed", border_style="red", box=box.HEAVY))
    Prompt.ask("Press Enter to close", default="")
    sys.exit(1)


def _folder_picker(title: str) -> str | None:
    """Return a folder path via GUI dialog or console prompt."""
    if _HAS_TKINTER:
        root = tk.Tk()
        root.withdraw()
        root.lift()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title=title)
        root.destroy()
        return folder if folder else None

    console.print(Panel(title, border_style="cyan", box=box.ROUNDED))
    raw = Prompt.ask("Paste folder path, or press Enter to cancel", default="")
    raw = raw.strip().strip('"').strip("'")
    if not raw:
        return None
    if not os.path.isdir(raw):
        console.print(f"[bold red]Path not found:[/] {raw}")
        return None
    return raw


def _banner() -> Panel:
    width = max(74, min(console.size.width - 4, 112))
    art_lines = [
        "   ____ ____ _____ ____     ___ _   _ _____ _____ _     ",
        "  / ___/ ___|_   _|  _ \\   |_ _| \\ | |_   _| ____| |    ",
        " | |  _\\___ \\ | | | |_) |   | ||  \\| | | | |  _| | |    ",
        " | |_| |___) || | |  _ <    | || |\\  | | | | |___| |___ ",
        "  \\____|____/ |_| |_| \\_\\  |___|_| \\_| |_| |_____|_____|",
        "  RETURN DATA EXTRACTION // RECONCILIATION // EXCEL INTELLIGENCE",
    ]
    art = Text()
    styles = ["#6fffe9", "#5bc0be", "#3a86ff", "#4361ee", "#7b2cbf", "#b5179e", "#f72585", "#ffb703"]
    for line, style in zip(art_lines, styles):
        art.append(line[:width].center(width), style=f"bold {style}")
        art.append("\n")

    meta = Table.grid(expand=True)
    meta.add_column(justify="left")
    meta.add_column(justify="center")
    meta.add_column(justify="right")
    meta.add_row(
        f"[bold white]{APP_NAME.upper()}[/]",
        "[#bde0fe]PDF EXTRACTION CONTROL DECK[/]",
        f"[dim]v{VERSION}[/]",
    )
    meta.add_row(
        "[dim]Parse returns[/]",
        "[dim]Normalize tables[/]",
        "[dim]Build Excel intelligence[/]",
    )

    return Panel(
        Group(Align.center(art), meta),
        border_style="#3a86ff",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
        expand=True,
    )


def _menu_panel() -> Panel:
    left = Table.grid(padding=(0, 1), expand=True)
    left.add_column("key", justify="right", style="bold #ffb703", no_wrap=True)
    left.add_column("value", ratio=1)
    left.add_row("01", "[bold white]GSTR-1[/]\n[dim]Outward supplies, liability reconciliation, HSN coverage[/]")
    left.add_row("02", "[bold white]GSTR-3B[/]\n[dim]Liability, ITC, payments, reverse charge review[/]")
    left.add_row("Q", "[bold white]Quit[/]\n[dim]Return to command line[/]")

    right = Table.grid(padding=(0, 1), expand=True)
    right.add_column("label", style="bold #8ecae6", no_wrap=True)
    right.add_column("value")
    right.add_row("INPUT", "GST portal PDF returns")
    right.add_row("ENGINE", "Parallel parser + rule checks")
    right.add_row("OUTPUT", "Review workbook + analytics workbook")
    right.add_row("MODE", "GUI folders or pasted paths")

    deck = Table.grid(expand=True)
    deck.add_column(ratio=2)
    deck.add_column(ratio=2)
    deck.add_row(
        Panel(left, title="Workflow", border_style="#ffb703", box=box.ROUNDED),
        Panel(right, title="Run Profile", border_style="#8ecae6", box=box.ROUNDED),
    )
    return Panel(deck, border_style="#5bc0be", box=box.HEAVY, padding=(1, 1), expand=True)


def print_main_menu() -> None:
    console.clear()
    console.print(_banner())
    console.print(_menu_panel())


def _selection_summary(workflow: str, input_dir: str, output_dir: str) -> None:
    table = Table(box=box.SIMPLE_HEAVY, expand=True, show_header=False)
    table.add_column("Field", style="bold #8ecae6", width=12)
    table.add_column("Path", style="white")
    table.add_row("Workflow", workflow)
    table.add_row("Input", input_dir)
    table.add_row("Output", output_dir)
    console.print(Panel(table, title="Execution Plan", border_style="#3a86ff", box=box.ROUNDED))


def _success_panel(workflow: str, review_path: str, analytics_path: str) -> None:
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Workbook", style="bold #8ecae6", width=14)
    table.add_column("Path", style="white")
    table.add_column("Size", justify="right", style="#ffb703", width=10)
    table.add_row("Review", review_path, f"{os.path.getsize(review_path) // 1024} KB")
    table.add_row("Analytics", analytics_path, f"{os.path.getsize(analytics_path) // 1024} KB")
    console.print(Panel(
        table,
        title=f"{workflow} Complete",
        subtitle="Excel workbooks generated",
        border_style="green",
        box=box.DOUBLE_EDGE,
    ))


def _error_panel(exc: Exception) -> None:
    console.print(Panel(
        f"[bold red]{type(exc).__name__}[/]\n\n{exc}",
        title="Run Failed",
        border_style="red",
        box=box.HEAVY,
    ))
    console.print_exception(show_locals=False)


def _run_workflow(
    workflow_name: str,
    input_title: str,
    output_folder_name: str,
    locked_files: list[str],
    runner,
) -> None:
    console.print(Panel(
        f"[bold white]{workflow_name}[/]\n[dim]Select the PDF source folder first.[/]",
        border_style="#8ecae6",
        box=box.ROUNDED,
    ))
    input_dir = _folder_picker(input_title)
    if not input_dir:
        console.print("[yellow]No folder selected. Returning to menu.[/]")
        return

    console.print(Panel(
        "[bold white]Choose where the generated workbooks should be saved.[/]\n"
        "[dim]Cancel to use the input folder.[/]",
        border_style="#8ecae6",
        box=box.ROUNDED,
    ))
    user_out_dir = _folder_picker("Select Output Folder (Cancel to use Input Folder)")
    base_out_dir = user_out_dir if user_out_dir else input_dir
    output_dir = os.path.join(base_out_dir, output_folder_name)

    locked_file = check_file_locks(output_dir, locked_files)
    if locked_file:
        console.print(Panel(
            f"Please close [bold]{locked_file}[/] in Excel first, then run again.",
            title="Workbook Locked",
            border_style="red",
            box=box.HEAVY,
        ))
        return

    _selection_summary(workflow_name, input_dir, output_dir)

    try:
        review_path, analytics_path = runner(input_dir, output_dir)
        _success_panel(workflow_name, review_path, analytics_path)
    except Exception as exc:
        _error_panel(exc)


def run_gstr1_cli() -> None:
    from .gstr1.pipeline import run_pipeline_gstr1
    _run_workflow(
        workflow_name="GSTR-1 Intelligence Run",
        input_title="Select Folder with GSTR-1 PDFs",
        output_folder_name="GSTR1_Verified_Reports",
        locked_files=["GSTR1_Auditor_Master.xlsx", "GSTR1_Analytics_Master.xlsx"],
        runner=run_pipeline_gstr1,
    )


def run_gstr3b_cli() -> None:
    from .gstr3b.pipeline import run_pipeline_gstr3b
    _run_workflow(
        workflow_name="GSTR-3B Intelligence Run",
        input_title="Select Folder with GSTR-3B PDFs",
        output_folder_name="GSTR3B_Verified_Reports",
        locked_files=["GSTR3B_Auditor_Master.xlsx", "GSTR3B_Analytics_Master.xlsx"],
        runner=run_pipeline_gstr3b,
    )


def main() -> None:
    _set_dpi_awareness()
    dependency_check()

    while True:
        print_main_menu()
        choice = Prompt.ask("[bold #ffb703]Command[/]", choices=["1", "01", "2", "02", "Q", "q"])
        choice = choice.upper()

        if choice in ("1", "01"):
            run_gstr1_cli()
            Prompt.ask("Press Enter to return to menu", default="")
        elif choice in ("2", "02"):
            run_gstr3b_cli()
            Prompt.ask("Press Enter to return to menu", default="")
        elif choice == "Q":
            console.print("[dim]Session closed.[/]")
            break

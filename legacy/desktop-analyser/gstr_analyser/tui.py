"""Textual TUI for the GSTR Return Analyser."""

import os
import sys
import traceback
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Input, ProgressBar, Static, Label

from . import APP_NAME, VERSION
from .ui import PipelineUI


class StrikingHeader(Static):
    """A striking block-text header for the application."""

    def render(self) -> Text:
        # GSTR ANALYSER in the requested blocky style with "sparkles"
        # Cadet Blue Accent: #5bc0be
        lines = [
            "  [dim]✧[/]      [#5bc0be]██████╗ ███████╗████████╗██████╗ [/]        [dim]*[/]",
            "       [#5bc0be]██╔════╝ ██╔════╝╚══██╔══╝██╔══██╗[/]    [dim]°[/]",
            "  [dim]*[/]    [#5bc0be]██║  ███╗███████╗   ██║   ██████╔╝[/]       [dim]✧[/]",
            "       [#5bc0be]██║   ██║╚════██║   ██║   ██╔══██╗[/]",
            "  [dim]°[/]    [#5bc0be]╚██████╔╝███████║   ██║   ██║  ██║[/]   [dim]*[/]",
            "       [#5bc0be] ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝ [/]",
            "",
            " [#c8c8c8]█████╗ ███╗   ██╗ █████╗ ██╗     ██╗   ██╗███████╗███████╗██████╗ [/]",
            " [#c8c8c8]██╔══██╗████╗  ██║██╔══██╗██║     ╚██╗ ██╔╝╚══███╔╝██╔════╝██╔══██╗[/]",
            " [#c8c8c8]███████║██╔██╗ ██║███████║██║      ╚████╔╝   ███╔╝ █████╗  ██████╔╝[/]",
            " [#c8c8c8]██╔══██║██║╚██╗██║██╔══██║██║       ╚██╔╝   ███╔╝  ██╔══╝  ██╔══██╗[/]",
            " [#c8c8c8]██║  ██║██║ ╚████║██║  ██║███████╗   ██║   ███████╗███████╗██║  ██║[/]",
            " [#c8c8c8]╚═╝  ╚═╝╚═╝  ╚███║╚═╝  ╚═╝╚══════╝   ╚═╝   ╚══════╝╚══════╝╚═╝  ╚═╝ [/]",
            "",
            f" [bold white]ELEVATED TAX ANALYTICS[/] [dim #555555]·[/] [white]PRECISION PDF EXTRACTION[/] [dim #555555]·[/] [#5bc0be]v{VERSION}[/]",
            " [dim #333333]──────────────────────────────────────────────────────────────────────────[/]",
        ]
        return Text.from_markup("\n".join(lines))


class _ChoiceView(Widget):
    """Keyboard-navigable single-choice list using reactive render()."""

    can_focus = True

    CHOICES = [
        ("GSTR-1 ", "Outward supplies · liability reconciliation · HSN coverage"),
        ("GSTR-3B", "Liability · ITC · payments · reverse charge review"),
    ]

    cursor: reactive[int] = reactive(0)

    def render(self) -> Text:
        lines = []
        for i, (label, desc) in enumerate(self.CHOICES):
            is_selected = i == self.cursor
            # Safe selection indicators: ▶ (cursor), ◉ (selected), ○ (unselected)
            marker = "▶" if is_selected else " "
            check = "◉" if is_selected else "○"
            
            if is_selected:
                lines.append(
                    f"  [bold #5bc0be]{marker}[/] [bold white]{check} {label}[/]  [dim]{desc}[/]"
                )
            else:
                lines.append(f"    [#c8c8c8]{check} {label}[/]  [dim]{desc}[/]")
        return Text.from_markup("\n".join(lines))

    def move(self, delta: int) -> None:
        self.cursor = max(0, min(len(self.CHOICES) - 1, self.cursor + delta))

    def selected_label(self) -> str:
        return self.CHOICES[self.cursor][0]

    def reset(self) -> None:
        self.cursor = 0


class GSTRAnalyserTUI(App):
    BINDINGS = [
        Binding("ctrl+s",  "run_pipeline", "Run"),
        Binding("escape",  "back",         "Back"),
        Binding("ctrl+q",  "quit",         "Quit"),
        Binding("alt+b",   "back",         "Back", show=False, priority=True),
        Binding("alt+n",   "confirm",      "Next", show=False, priority=True),
        Binding("enter",   "confirm",      "Confirm", show=True),
        Binding("b",       "go_back_key",  "Back", show=True),
        Binding("n",       "go_next_key",  "Next", show=True),
        Binding("up",      "cursor_up",    show=False),
        Binding("down",    "cursor_down",  show=False),
    ]

    CSS = """
    Screen        { background: #000000; color: #ffffff; align: center top; }
    #root         { layout: vertical; width: 100%; max-width: 120; height: auto; padding: 1 2; }

    StrikingHeader { margin-bottom: 1; height: auto; }
    
    #step_info    { background: #080808; padding: 0 1; margin-bottom: 1; height: auto; border-left: solid #5bc0be; }
    #question     { text-style: bold; margin-bottom: 1; height: auto; color: #ffffff; }

    #choice_view  { border: solid #444444; padding: 1 1; margin-bottom: 1; height: auto; min-height: 4; }
    #choice_view:focus { border: solid #ffffff; }

    #path_row     { layout: horizontal; height: 3; margin-bottom: 1; }
    #text_input   { width: 1fr; border: solid #666666; background: #000000; }
    #text_input:focus { border: solid #ffffff; }
    #browse_btn   { width: 7; height: 3; border: solid #666666; background: #080808;
                    margin-left: 1; margin-right: 0; min-width: 7; }
    #browse_btn:focus { border: solid #ffffff; }

    #review_view  { border: solid #444444; padding: 1 1; margin-bottom: 1; height: auto; min-height: 4; }

    #progress_bar { width: 100%; margin-bottom: 1; height: 1; }
    ProgressBar > .bar--complete { color: #ffffff; }
    ProgressBar > .bar--indeterminate { color: #ffffff; }
    ProgressBar > .percentage { display: none; }

    #run_container { height: auto; margin-bottom: 1; background: #080808; padding: 1 2; border: solid #666666; }
    #stage_table { height: auto; margin-bottom: 0; background: #080808; color: #ffffff; }
    #stage_table > .datatable--header { color: #888888; text-style: none; background: #080808; }
    #stage_table > .datatable--cursor { background: #080808; color: #ffffff; }
    #stage_table > .datatable--even-row { background: #080808; }
    #stage_table > .datatable--odd-row { background: #080808; }
    #summary_view { height: auto; margin-top: 1; display: none; }

    #buttons      { layout: horizontal; height: 3; margin-bottom: 1; }
    Button        { width: 18; border: solid #666666; background: #111111; margin-right: 1; color: #ffffff; }
    Button:focus  { border: solid #ffffff; }
    Button:disabled { color: #444444; border: solid #333333; }

    .hidden { display: none; }
    """

    _STEPS = [
        ("return_type", "Return Type",   "choice"),
        ("input_dir",   "Input Folder",  "text"),
        ("output_dir",  "Output Folder", "text"),
        ("review",      "Review",        "review"),
        ("run",         "Run",           "run"),
    ]

    def __init__(self):
        super().__init__()
        self.step_index: int = 0
        self.return_type: str = "gstr1"
        self.input_dir: str = ""
        self.output_dir: str = _get_downloads_folder()
        self.text_entry_mode: bool = False
        self._pipeline_running: bool = False
        self._run_done: bool = False
        self._total_files: int = 0
        self._exception_count: int = 0

    # ------------------------------------------------------------------ compose

    def compose(self) -> ComposeResult:
        with Vertical(id="root"):
            yield StrikingHeader()
            yield Static("", id="step_info")
            yield Static("", id="question")
            yield _ChoiceView(id="choice_view")
            with Horizontal(id="path_row"):
                yield Input(placeholder="Paste or type folder path…", id="text_input")
                yield Button("+", id="browse_btn", tooltip="Open folder picker")
            yield Static("", id="review_view")
            yield ProgressBar(id="progress_bar", show_eta=False, show_percentage=False)
            with Vertical(id="run_container", classes="hidden"):
                yield DataTable(id="stage_table", show_cursor=False)
                yield Static("", id="summary_view")
            with Horizontal(id="buttons"):
                yield Button("[underline]B[/underline]ack", id="back_btn", disabled=True)
                yield Button("[underline]N[/underline]ext", id="next_btn")
        yield Footer()

    # ------------------------------------------------------------------ mount

    def on_mount(self) -> None:
        # Cache references
        self._step_info   = self.query_one("#step_info",   Static)
        self._question    = self.query_one("#question",    Static)
        self._choice_view = self.query_one("#choice_view", _ChoiceView)
        self._path_row    = self.query_one("#path_row",    Horizontal)
        self._text_input  = self.query_one("#text_input",  Input)
        self._review_view = self.query_one("#review_view", Static)
        self._progress    = self.query_one("#progress_bar", ProgressBar)
        self._run_container = self.query_one("#run_container", Vertical)
        self._stage_table = self.query_one("#stage_table", DataTable)
        self._summary_view = self.query_one("#summary_view", Static)
        self._back_btn    = self.query_one("#back_btn",    Button)
        self._next_btn    = self.query_one("#next_btn",    Button)

        # Configure DataTable columns once — fixed widths pin the right edge
        self._stage_table.add_column("  ", width=4, key="icon")
        self._stage_table.add_column("Stage", width=35, key="stage")
        self._stage_table.add_column("Exceptions", width=12, key="exc")
        self._stage_table.fixed_columns = 0

        self._refresh_step()
        self._check_deps()

    # ------------------------------------------------------------------ dep check

    def _check_deps(self) -> None:
        required = ["pdfplumber", "pandas", "numpy", "xlsxwriter", "rich"]
        missing = [pkg for pkg in required if not _can_import(pkg)]
        if missing:
            self._question.update(
                f"[bold red]Missing packages:[/] {', '.join(missing)}\n"
                f"[dim]Fix:  pip install {' '.join(missing)}[/]"
            )
            self._next_btn.disabled = True

    # ------------------------------------------------------------------ step helpers

    def _step_id(self) -> str:
        return self._STEPS[self.step_index][0]

    def _step_type(self) -> str:
        return self._STEPS[self.step_index][2]

    def _refresh_step(self) -> None:
        step_id, step_name, step_type = self._STEPS[self.step_index]
        total = len(self._STEPS)

        self._step_info.update(
            f"[#bfbfbf]Step {self.step_index + 1} of {total}[/]"
            f"  [bold white]{step_name}[/]"
        )

        is_choice = step_type == "choice"
        is_text   = step_type == "text"
        is_review = step_type == "review"
        is_run    = step_type == "run"

        self._choice_view.set_class(not is_choice, "hidden")
        self._path_row.set_class(not is_text,    "hidden")
        self._review_view.set_class(not is_review, "hidden")
        self._run_container.set_class(not is_run, "hidden")
        self._progress.set_class(not is_run, "hidden")

        self.text_entry_mode = is_text

        if step_id == "return_type":
            self._question.update("[bold]Which return type do you want to process?[/]")
            self._back_btn.disabled = True
            self._next_btn.disabled = False
            self._next_btn.label = "[underline]N[/underline]ext"
            self._choice_view.focus()

        elif step_id == "input_dir":
            self._question.update("📁 [bold]Input folder — path to folder containing GSTR PDF files[/]")
            self._text_input.value = self.input_dir
            self._back_btn.disabled = False
            self._next_btn.disabled = False
            self._next_btn.label = "[underline]N[/underline]ext"
            self._text_input.focus()

        elif step_id == "output_dir":
            self._question.update("📁 [bold]Output folder — where workbooks will be saved[/]")
            self._text_input.value = self.output_dir
            self._back_btn.disabled = False
            self._next_btn.disabled = False
            self._next_btn.label = "[underline]N[/underline]ext"
            self._text_input.focus()

        elif step_id == "review":
            rt_label = "GSTR-1" if self.return_type == "gstr1" else "GSTR-3B"
            eff_out = self.output_dir if self.output_dir else self.input_dir
            folder = "GSTR1_Verified_Reports" if self.return_type == "gstr1" else "GSTR3B_Verified_Reports"
            
            # Escape paths to prevent Rich markup issues
            esc_input = escape(self.input_dir)
            esc_output = escape(os.path.join(eff_out, folder))

            self._question.update("[bold]Review — confirm before running[/]")
            self._review_view.update(
                f"  📄 [bold #5bc0be]Workflow[/]   {rt_label}\n"
                f"  📁 [bold #5bc0be]Input[/]      {esc_input}\n"
                f"  📁 [bold #5bc0be]Output[/]     {esc_output}"
            )
            self._back_btn.disabled = False
            self._next_btn.disabled = False
            self._next_btn.label = "Run  Ctrl+S"
            self._next_btn.focus()

        elif step_id == "run":
            self._question.update("[bold]Running pipeline…[/]")
            self._back_btn.disabled = True
            self._next_btn.disabled = True
            self._next_btn.label = "[underline]N[/underline]ext"

    # ------------------------------------------------------------------ navigation

    def _advance(self) -> None:
        step_id = self._step_id()

        if step_id == "return_type":
            label = self._choice_view.selected_label()
            self.return_type = "gstr1" if label == "GSTR-1" else "gstr3b"

        elif step_id == "input_dir":
            raw = self._text_input.value.strip().strip('"').strip("'")
            if not os.path.isdir(raw):
                self._question.update(
                    f"[bold red]Folder not found:[/] {raw or '(empty)'}\n"
                    "Check the path and press Enter again  ·  Esc to go back"
                )
                return
            self.input_dir = raw

        elif step_id == "output_dir":
            raw = self._text_input.value.strip().strip('"').strip("'")
            if raw and not os.path.isdir(raw):
                self._question.update(
                    f"[bold red]Folder not found:[/] {raw}\n"
                    "Leave blank for input folder, or fix the path  ·  Esc to go back"
                )
                return
            self.output_dir = raw

        elif step_id == "review":
            self._start_run()
            return

        elif step_id == "run" and self._run_done:
            self._reset()
            return

        if self.step_index < len(self._STEPS) - 1:
            self.step_index += 1
            self._refresh_step()

    def _go_back(self) -> None:
        if self._pipeline_running:
            return
        if self.step_index > 0:
            self._run_done = False
            self.step_index -= 1
            self._refresh_step()

    def _reset(self) -> None:
        self.step_index = 0
        self.return_type = "gstr1"
        self.input_dir = ""
        self.output_dir = ""
        self._run_done = False
        self._choice_view.reset()
        self._refresh_step()

    # ------------------------------------------------------------------ action bindings

    def check_action(self, action: str, parameters) -> bool:
        if action in ("back", "quit", "confirm"):
            return True
        if action in ("go_back_key", "go_next_key"):
            # Plain b/n keys should be typed into Input during text entry
            return not self.text_entry_mode
        if action in ("cursor_up", "cursor_down"):
            return self._step_type() == "choice"
        if action == "run_pipeline":
            return self._step_id() == "review"
        return True

    def action_back(self) -> None:
        self._go_back()

    def action_confirm(self) -> None:
        self._advance()

    def action_cursor_up(self) -> None:
        self._choice_view.move(-1)

    def action_cursor_down(self) -> None:
        self._choice_view.move(1)

    def action_go_back_key(self) -> None:
        self._go_back()

    def action_go_next_key(self) -> None:
        self._advance()

    def action_run_pipeline(self) -> None:
        if self._step_id() == "review":
            self._start_run()

    # ------------------------------------------------------------------ widget events

    @on(Button.Pressed, "#back_btn")
    def _handle_back(self) -> None:
        self._go_back()

    @on(Button.Pressed, "#next_btn")
    def _handle_next(self) -> None:
        self._advance()

    @on(Button.Pressed, "#browse_btn")
    def _handle_browse(self) -> None:
        step_id = self._step_id()
        title = (
            "Select folder with GSTR PDF files"
            if step_id == "input_dir"
            else "Select output folder"
        )
        folder = _pick_folder(title)
        if folder:
            self._text_input.value = folder
        self._text_input.focus()

    @on(Input.Submitted)
    def _handle_input_submitted(self) -> None:
        self._advance()

    # ------------------------------------------------------------------ run

    def _start_run(self) -> None:
        eff_out = self.output_dir if self.output_dir else self.input_dir
        folder = "GSTR1_Verified_Reports" if self.return_type == "gstr1" else "GSTR3B_Verified_Reports"
        self._actual_output_dir = os.path.join(eff_out, folder)

        self.step_index = len(self._STEPS) - 1
        self._refresh_step()

        self._total_files = 0
        self._exception_count = 0

        # Define pipeline stages
        self._stage_labels = [
            "Table extraction",
            "Sanity checks",
            "Analytics creation",
            "Workbook compilation",
        ]

        # Populate the DataTable — clear rows, keep columns
        self._stage_table.clear()
        self._row_keys = []
        for label in self._stage_labels:
            key = self._stage_table.add_row("✗", label, "—", key=label)
            self._row_keys.append(label)

        # Height = number of rows + 1 (header)
        self._stage_table.styles.height = len(self._stage_labels) + 1

        self._progress.update(total=len(self._stage_labels), progress=0)
        self._summary_view.styles.display = "none"
        self._summary_view.update("")

        self._pipeline_running = True
        self._run_done = False
        self._run_worker(self.input_dir, self._actual_output_dir)

    @work(exclusive=True, thread=True)
    def _run_worker(self, input_dir: str, output_dir: str) -> None:
        from .gstr1.pipeline import run_pipeline_gstr1
        from .gstr3b.pipeline import run_pipeline_gstr3b

        step_names = PipelineUI.STEPS

        def cb(step: int, detail: str) -> None:
            # Track metrics from detail strings emitted by the pipeline
            if "Found" in detail and "PDF" in detail:
                try: self._total_files = int(detail.split()[1])
                except: pass
            if "exception" in detail:
                try: self._exception_count += int(detail.split()[0])
                except: pass

            def _mark_row(label: str, exc_val: int):
                try:
                    self._stage_table.update_cell(label, "exc", str(exc_val))
                    self._stage_table.update_cell(label, "icon", "✔")
                except Exception:
                    pass

            if step == 2:
                self.call_from_thread(_mark_row, "Table extraction", 0)
                self.call_from_thread(_mark_row, "Sanity checks", self._exception_count)
                self.call_from_thread(self._progress.update, progress=2)
            elif step == 3:
                self.call_from_thread(_mark_row, "Analytics creation", 0)
                self.call_from_thread(self._progress.update, progress=3)
            elif step == 5:
                self.call_from_thread(_mark_row, "Workbook compilation", 0)
                self.call_from_thread(self._progress.update, progress=4)

        try:
            runner = run_pipeline_gstr1 if self.return_type == "gstr1" else run_pipeline_gstr3b
            review_path, analytics_path = runner(input_dir, output_dir, progress_cb=cb)
            self.call_from_thread(self._on_success, review_path, analytics_path)
        except Exception as exc:
            tb = traceback.format_exc()
            self.call_from_thread(self._on_error, exc, tb)

    def _on_success(self, review_path: str, analytics_path: str) -> None:
        self._pipeline_running = False
        self._run_done = True

        self._progress.update(progress=len(self._stage_labels))
        self._summary_view.update(
            f"[dim]Input folder  :[/] [white]{self.input_dir}[/]\n"
            f"[dim]Output folder :[/] [white]{self._actual_output_dir}[/]\n\n"
            f"[bold white]Process complete.[/]"
        )
        self._summary_view.styles.display = "block"

        self._question.update("[bold white]Pipeline complete.[/]")
        self._back_btn.disabled = False
        self._next_btn.label = "Run Again"
        self._next_btn.disabled = False

    def _on_error(self, exc: Exception, tb: str) -> None:
        self._pipeline_running = False
        self._run_done = True

        self._summary_view.update(
            f"[dim]Input folder  :[/] [white]{self.input_dir}[/]\n"
            f"[dim]Output folder :[/] [white]{self._actual_output_dir}[/]\n\n"
            f"[dim white]Pipeline halted — check exceptions above.[/]"
        )
        self._summary_view.styles.display = "block"

        self._question.update("[bold white]Pipeline complete.[/]")
        self._back_btn.disabled = False
        self._next_btn.label = "Run Again"
        self._next_btn.disabled = False


# ------------------------------------------------------------------ module-level helpers

def _get_downloads_folder() -> str:
    """Read the actual Downloads folder location, accounting for Windows relocation."""
    default = str(Path.home() / "Downloads")
    if sys.platform != "win32":
        return default
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        val_name = "{374DE290-123F-4565-9164-39C4925E467B}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            return str(winreg.QueryValueEx(key, val_name)[0])
    except Exception:
        return default


def _pick_folder(title: str = "Select Folder") -> str | None:
    """Open a native folder picker dialog. Returns path or None if cancelled."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        _set_dpi_awareness()
        root = tk.Tk()
        root.withdraw()
        root.lift()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title=title)
        root.destroy()
        return folder if folder else None
    except Exception:
        return None


def _set_dpi_awareness() -> None:
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


def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def run_tui() -> None:
    _set_dpi_awareness()
    GSTRAnalyserTUI().run()

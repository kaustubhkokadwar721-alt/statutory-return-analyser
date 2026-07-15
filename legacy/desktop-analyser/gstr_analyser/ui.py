"""Terminal UI and Excel formatting helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class PipelineUI:
    STEPS = [
        "Validate PDFs",
        "Extract Tables",
        "Run Checks",
        "Shape Analytics",
        "Write Workbooks",
    ]

    def __init__(self, title: str = "GSTR Return Analyser"):
        self.title = title
        self.current_step = 0
        self.detail = ""

    def advance(self, detail: str = "") -> None:
        self.current_step += 1
        self.detail = detail

    def _status_cards(self) -> Columns:
        cards = []
        for idx, step in enumerate(self.STEPS):
            if idx < self.current_step:
                border = "green"
                state = Text("COMPLETE", style="bold green")
                marker = "[+]"
            elif idx == self.current_step:
                border = "#ffb703"
                state = Text("ACTIVE", style="bold #ffb703")
                marker = "[>]"
            else:
                border = "grey35"
                state = Text("WAITING", style="dim")
                marker = "[ ]"

            body = Table.grid(expand=True)
            body.add_column(justify="left")
            body.add_row(f"[bold]{marker} {idx + 1:02d}[/]")
            body.add_row(f"[white]{step}[/]")
            body.add_row(state)
            cards.append(Panel(body, border_style=border, box=box.ROUNDED, padding=(0, 1)))
        return Columns(cards, equal=True, expand=True)

    def _progress_bar(self) -> Text:
        total = len(self.STEPS)
        done = min(self.current_step, total)
        width = 28
        filled = int(width * done / total)
        bar = Text()
        bar.append("[", style="dim")
        bar.append("#" * filled, style="bold #3a86ff")
        bar.append("-" * (width - filled), style="grey35")
        bar.append("]", style="dim")
        bar.append(f" {done}/{total}", style="bold white")
        return bar

    def render(self) -> Panel:
        header = Table.grid(expand=True)
        header.add_column(justify="left", ratio=2)
        header.add_column(justify="right", ratio=1)
        header.add_row(
            f"[bold white]{self.title.upper()}[/]",
            "[#8ecae6]LIVE RUN[/]",
        )
        header.add_row(
            "[dim]Extraction control deck[/]",
            "[dim]Pipeline[/]",
        )

        progress_panel = Panel(
            Align.left(self._progress_bar()),
            title="Progress",
            border_style="grey35",
            box=box.ROUNDED,
            padding=(0, 1),
        )

        detail_panel = Panel(
            Align.left(Text(self.detail or "Working...", style="bold white")),
            title="Current Signal",
            border_style="#3a86ff",
            box=box.ROUNDED,
            padding=(0, 1),
        )

        return Panel(
            Group(header, progress_panel, self._status_cards(), detail_panel),
            border_style="#5bc0be",
            box=box.DOUBLE_EDGE,
            expand=True,
            padding=(1, 2),
        )


def apply_header_format(writer, sheet_name: str, df: pd.DataFrame) -> None:
    """Overwrite row 0 with a bold dark-blue header on an xlsxwriter sheet."""
    wb = writer.book
    ws = writer.sheets[sheet_name]
    fmt = wb.add_format({
        "bold": True,
        "bg_color": "#1F4E78",
        "font_color": "white",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
    })
    for col_num, col_name in enumerate(df.columns):
        ws.write(0, col_num, col_name, fmt)


def format_column_widths(writer, sheet_name: str, df: pd.DataFrame, min_width: int = 12) -> None:
    """Auto-size every column to max(header length, max data length)."""
    ws = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        header_len = len(str(col))
        data_max = df[col].fillna("").astype(str).apply(len).max() if not df.empty else 0
        ws.set_column(i, i, max(min_width, header_len + 2, int(data_max) + 2))


def freeze_top_row(writer, sheet_name: str) -> None:
    writer.sheets[sheet_name].freeze_panes(1, 0)


_INDIAN_NUM_FMT = "##,##,##0"       # whole-rupee Indian comma grouping
_DATE_PERIOD_FMT = "mmm-yy"         # Apr-25 style

# Column-name substrings that indicate money values
_MONEY_KEYWORDS = (
    "value", "tax", "paid", "amount", "liability", "itc",
    "cash", "variance", "declared", "claimed", "rcm", "igst",
    "cgst", "sgst", "cess", "computed", "reported",
)


def sort_dataframe(df: "pd.DataFrame") -> "pd.DataFrame":
    """Return df sorted Period_Year asc, then GSTIN/Source_File.

    Period_Year strings ('Apr-25', 'Apr 2025') are parsed to dates for ordering;
    unparseable values sort to the end.
    """
    import pandas as pd
    if df is None or df.empty:
        return df
    result = df.copy()
    sort_cols: list[str] = []
    if "Period_Year" in result.columns:
        result["_sort_period"] = pd.to_datetime(
            result["Period_Year"].astype(str), format="%b-%y", errors="coerce"
        ).fillna(
            pd.to_datetime(result["Period_Year"].astype(str), format="%b %Y", errors="coerce")
        )
        sort_cols.append("_sort_period")
    for extra in ("GSTIN", "Source_File"):
        if extra in result.columns:
            sort_cols.append(extra)
    if sort_cols:
        result = result.sort_values(sort_cols, na_position="last").drop(
            columns=[c for c in ("_sort_period",) if c in result.columns]
        ).reset_index(drop=True)
    return result


def apply_period_date_format(writer, sheet_name: str, df: "pd.DataFrame") -> None:
    """Apply mmm-yy date format to the Period_Year column if present."""
    if "Period_Year" not in df.columns:
        return
    import pandas as pd
    wb = writer.book
    ws = writer.sheets[sheet_name]
    date_fmt = wb.add_format({"num_format": _DATE_PERIOD_FMT, "border": 1})
    col_idx = list(df.columns).index("Period_Year")
    for row_num, val in enumerate(df["Period_Year"], start=1):
        p = pd.to_datetime(str(val), format="%b-%y", errors="coerce")
        if pd.isna(p):
            p = pd.to_datetime(str(val), format="%b %Y", errors="coerce")
        if not pd.isna(p):
            ws.write_datetime(row_num, col_idx, p.to_pydatetime(), date_fmt)


def apply_indian_number_format(writer, sheet_name: str, df: "pd.DataFrame") -> None:
    """Apply Indian whole-rupee number format (##,##,##0) to money-like numeric columns."""
    import pandas as pd
    wb = writer.book
    ws = writer.sheets[sheet_name]
    num_fmt = wb.add_format({"num_format": _INDIAN_NUM_FMT, "border": 1})
    for col_idx, col_name in enumerate(df.columns):
        lower = str(col_name).lower()
        if not any(kw in lower for kw in _MONEY_KEYWORDS):
            continue
        if not pd.api.types.is_numeric_dtype(df[col_name]):
            continue
        for row_num, val in enumerate(df[col_name], start=1):
            if pd.notna(val):
                ws.write_number(row_num, col_idx, float(val), num_fmt)


def apply_all_borders(writer, sheet_name: str, df: "pd.DataFrame") -> None:
    """Stamp every data cell (rows 1..n) with a plain thin border.

    Called before the specialised date/number formatters so those can
    overwrite with their own border+format without leaving any column bare.
    """
    import pandas as pd
    wb = writer.book
    ws = writer.sheets[sheet_name]
    plain_fmt = wb.add_format({"border": 1})
    for row_num, row_vals in enumerate(df.itertuples(index=False), start=1):
        for col_idx, val in enumerate(row_vals):
            try:
                if pd.isna(val):
                    ws.write_blank(row_num, col_idx, None, plain_fmt)
                    continue
            except (TypeError, ValueError):
                pass
            ws.write(row_num, col_idx, val, plain_fmt)


def write_sheet(
    writer,
    df: "pd.DataFrame",
    sheet_name: str,
    pass_col: str = None,
    pass_fmt=None,
    fail_fmt=None,
    sort: bool = True,
) -> None:
    """Write a DataFrame to an Excel sheet with header, widths, freeze, date and money formats."""
    if df is None or df.empty:
        return
    if sort:
        df = sort_dataframe(df)
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    apply_header_format(writer, sheet_name, df)
    format_column_widths(writer, sheet_name, df)
    freeze_top_row(writer, sheet_name)
    apply_all_borders(writer, sheet_name, df)        # uniform border first
    apply_period_date_format(writer, sheet_name, df)  # overwrites date cells
    apply_indian_number_format(writer, sheet_name, df)  # overwrites money cells
    if pass_col and pass_col in df.columns and pass_fmt and fail_fmt:
        ws = writer.sheets[sheet_name]
        col_idx = list(df.columns).index(pass_col)
        for row_num, val in enumerate(df[pass_col], start=1):
            fmt = pass_fmt if str(val).upper() in ("PASS", "YES") else fail_fmt
            ws.write(row_num, col_idx, val, fmt)

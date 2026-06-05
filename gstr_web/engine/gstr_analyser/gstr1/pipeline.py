"""GSTR-1 end-to-end pipeline."""

import glob
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from threading import Lock
from typing import Callable

import pandas as pd
from rich.live import Live

from ..cache import _cache_key, _copy_result, _load_cache, _save_cache
from ..exceptions import ExcelWriteError
from ..ui import apply_header_format, format_column_widths, freeze_top_row, write_sheet
from ..ui import PipelineUI
from .analytics import (
    build_executive_summary_gstr1,
    build_liability_recon,
    create_fact_table_gstr1,
)
from .checks import run_sanity_checks_gstr1
from .parser import parse_gstr1

_META_COLS = [
    "Source_File", "GSTIN", "Legal_Name", "Trade_Name",
    "FY", "Period", "Period_Year", "ARN", "ARN_Date",
]

_CONTEXT_FIELDS = ["GSTIN", "Period", "FY", "Period_Year", "Source_File"]


def _parse_one_gstr1(fpath: str, cache: dict, cache_lock: Lock):
    key = _cache_key(fpath)
    with cache_lock:
        cached = cache.get(key)
    if cached is not None:
        return _copy_result(cached), []

    local_errors = []
    result = parse_gstr1(fpath, local_errors)
    if result is not None:
        with cache_lock:
            cache[key] = result
    return _copy_result(result), local_errors


def _with_context(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    result = df.copy()
    for col in _CONTEXT_FIELDS:
        if col in result.columns:
            result.rename(columns={col: f"Raw_{col}"}, inplace=True)
    for col in reversed(_CONTEXT_FIELDS):
        result.insert(0, col, meta.get(col, ""))
    return result


def _write_status_format(writer, sheet_name: str, df: pd.DataFrame, status_col: str, formats: dict) -> None:
    if df.empty or status_col not in df.columns:
        return
    ws = writer.sheets[sheet_name]
    col_idx = list(df.columns).index(status_col)
    default_fmt = formats.get("FAIL") or next(iter(formats.values()))
    for row_num, val in enumerate(df[status_col], start=1):
        fmt = formats.get(str(val).upper(), default_fmt)
        ws.write(row_num, col_idx, val, fmt)


def _write_formatted_sheet(writer, df: pd.DataFrame, sheet_name: str) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    apply_header_format(writer, sheet_name, df)
    format_column_widths(writer, sheet_name, df)
    freeze_top_row(writer, sheet_name)


def run_pipeline_gstr1(input_folder: str, output_dir: str, progress_cb: Callable | None = None):
    """Run the GSTR-1 pipeline.

    progress_cb(step, detail) is called after each pipeline stage when provided.
    When None, a Rich Live panel is rendered in the terminal (original behaviour).
    """
    os.makedirs(output_dir, exist_ok=True)
    error_log = []
    ui = PipelineUI("GSTR-1 Return Analyser")

    # _live holds the Live context so _push can update it; None in TUI/callback mode.
    _live: list = [None]

    def _push() -> None:
        if _live[0] is not None:
            _live[0].update(ui.render())
        if progress_cb is not None:
            progress_cb(ui.current_step, ui.detail)

    ctx = Live(ui.render(), refresh_per_second=10) if progress_cb is None else nullcontext()
    with ctx as live:
        _live[0] = live

        ui.current_step = 0
        pdf_files = sorted(glob.glob(os.path.join(input_folder, "*.pdf")))
        if not pdf_files:
            raise FileNotFoundError("No PDF files found in the selected folder.")
        ui.detail = f"Found {len(pdf_files)} PDF(s)"
        _push()

        ui.advance("Reading PDF files...")
        _push()

        cache_file = os.path.join(output_dir, ".parse_cache.pkl")
        cache = _load_cache(cache_file)
        cache_lock = Lock()

        all_meta, all_raw, all_totals, all_coverage, all_exceptions = [], [], [], [], []
        done_count = 0

        with ThreadPoolExecutor(max_workers=min(4, len(pdf_files))) as executor:
            futures = {executor.submit(_parse_one_gstr1, f, cache, cache_lock): f for f in pdf_files}
            for future in as_completed(futures):
                fpath = futures[future]
                fname = os.path.basename(fpath)
                done_count += 1
                ui.detail = f"{done_count}/{len(pdf_files)}  {(fname[:30] + '...') if len(fname) > 30 else fname}"
                _push()

                try:
                    result, local_errors = future.result()
                except Exception as exc:
                    error_log.append({
                        "File": fname,
                        "Error_Type": type(exc).__name__,
                        "Message": str(exc),
                        "Action": "Could not process this file. Skipped.",
                    })
                    continue

                error_log.extend(local_errors)
                if result is None:
                    continue

                meta = dict(result["Metadata"])
                meta["Source_File"] = fname

                for key in ("Raw_Rows", "Section_Totals", "Table_Coverage"):
                    result[key] = _with_context(result[key], meta)

                all_meta.append(meta)
                all_raw.append(result["Raw_Rows"])
                all_totals.append(result["Section_Totals"])
                all_coverage.append(result["Table_Coverage"])

                try:
                    file_exceptions = run_sanity_checks_gstr1(result["Section_Totals"], meta)
                except Exception as exc:
                    error_log.append({
                        "File": fname,
                        "Error_Type": type(exc).__name__,
                        "Message": f"Sanity checks failed: {exc}",
                        "Action": "Checks skipped for this file. Data still written.",
                    })
                    file_exceptions = []
                for exc in file_exceptions:
                    exc["Source_File"] = fname
                all_exceptions.extend(file_exceptions)

        _save_cache(cache_file, cache)

        df_meta = pd.DataFrame(all_meta)
        df_raw = pd.concat(all_raw, ignore_index=True) if all_raw else pd.DataFrame()
        df_totals = pd.concat(all_totals, ignore_index=True) if all_totals else pd.DataFrame()
        df_coverage = pd.concat(all_coverage, ignore_index=True) if all_coverage else pd.DataFrame()

        ui.advance(f"{len(all_exceptions)} exception(s) flagged")
        _push()

        ui.advance("Building analytics fact tables...")
        _push()

        try:
            fact_df  = create_fact_table_gstr1(df_totals) if not df_totals.empty else pd.DataFrame()
            recon_df = build_liability_recon(df_totals, df_meta) if not df_totals.empty else pd.DataFrame()
        except Exception as exc:
            error_log.append({
                "File": "pipeline",
                "Error_Type": type(exc).__name__,
                "Message": f"Analytics build failed: {exc}",
                "Action": "Analytics sheets will be empty.",
            })
            fact_df  = pd.DataFrame()
            recon_df = pd.DataFrame()
        df_meta_out = df_meta[[c for c in _META_COLS if c in df_meta.columns]] if not df_meta.empty else pd.DataFrame()

        ui.advance("Writing workbooks...")
        _push()

        auditor_path = os.path.join(output_dir, "GSTR1_Auditor_Master.xlsx")
        analytics_path = os.path.join(output_dir, "GSTR1_Analytics_Master.xlsx")

        try:
            with pd.ExcelWriter(auditor_path, engine="xlsxwriter") as writer:
                wb = writer.book
                status_formats = {
                    "PASS": wb.add_format({"font_color": "green", "bold": True}),
                    "FAIL": wb.add_format({"font_color": "red", "bold": True}),
                    "WARN": wb.add_format({"font_color": "#CC7700", "bold": True}),
                }

                if error_log:
                    write_sheet(writer, pd.DataFrame(error_log), "ERRORS_LOG")

                write_sheet(writer, df_meta_out, "Metadata_Master")

                if all_exceptions:
                    df_exc = pd.DataFrame(all_exceptions)
                    _write_formatted_sheet(writer, df_exc, "EXCEPTIONS_LOG")
                    _write_status_format(writer, "EXCEPTIONS_LOG", df_exc, "Status", status_formats)

                if not df_coverage.empty:
                    _write_formatted_sheet(writer, df_coverage, "Table_Coverage")
                    coverage_formats = {"YES": status_formats["PASS"], "NO": status_formats["FAIL"]}
                    _write_status_format(writer, "Table_Coverage", df_coverage, "Has_Data", coverage_formats)

                if not recon_df.empty:
                    _write_formatted_sheet(writer, recon_df, "Liability_Recon")
                    _write_status_format(writer, "Liability_Recon", recon_df, "Status", status_formats)

                write_sheet(writer, df_raw, "Raw_Summary_Table")
                write_sheet(writer, df_totals, "Section_Totals")
        except ExcelWriteError:
            raise
        except Exception as exc:
            raise ExcelWriteError(
                f"Could not write '{os.path.basename(auditor_path)}'. "
                f"If it is open in Excel, close it and try again. ({exc})"
            ) from exc

        try:
            with pd.ExcelWriter(analytics_path, engine="xlsxwriter") as writer:
                build_executive_summary_gstr1(writer, df_meta_out, len(all_exceptions))
                write_sheet(writer, df_meta_out, "Dim_Taxpayer_Calendar")
                write_sheet(writer, fact_df, "Fact_Liability")
        except ExcelWriteError:
            raise
        except Exception as exc:
            raise ExcelWriteError(
                f"Could not write '{os.path.basename(analytics_path)}'. "
                f"If it is open in Excel, close it and try again. ({exc})"
            ) from exc

        ui.current_step = len(ui.STEPS)
        ui.detail = ""
        _push()

    return auditor_path, analytics_path

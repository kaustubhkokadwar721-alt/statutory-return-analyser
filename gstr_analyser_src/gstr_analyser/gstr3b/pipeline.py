"""GSTR-3B end-to-end pipeline."""

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
from ..ui import PipelineUI, apply_header_format, format_column_widths, freeze_top_row, write_sheet
from .analytics import create_analytics_schema_gstr3b, build_executive_summary_gstr3b
from .checks import run_sanity_checks_gstr3b
from .parser import parse_complete_gstr3b

_META_COLS = [
    "Source_File", "Period_Year", "Year", "Period", "GSTIN",
    "Legal_Name", "Trade_Name", "ARN", "Date_of_ARN",
]

_TABLE_NAMES = [
    "Table_3_1", "Table_3_1_1", "Table_3_2", "Table_4_ITC",
    "Table_5", "Table_5_1", "Table_6_1", "Table_Breakup",
]

_KNOWN_CHECKS = [
    "Payment_Recon_6_1",
    "ITC_Math_Integrated_tax",
    "ITC_Math_Central_tax",
    "ITC_Math_State_UT_tax",
    "ITC_Math_Cess",
    "RCM_CrossCheck",
]

_CONTEXT_FIELDS = ["GSTIN", "Period", "Year", "Period_Year", "Source_File"]


def _parse_one_gstr3b(fpath: str, cache: dict, cache_lock: Lock):
    key = _cache_key(fpath)
    with cache_lock:
        cached = cache.get(key)
    if cached is not None:
        return _copy_result(cached), []

    local_errors = []
    result = parse_complete_gstr3b(fpath, local_errors)
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
        result.insert(0, col, meta.get(col, "N/A"))
    return result


def _write_formatted_sheet(writer, df: pd.DataFrame, sheet_name: str) -> None:
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    apply_header_format(writer, sheet_name, df)
    format_column_widths(writer, sheet_name, df)
    freeze_top_row(writer, sheet_name)


def _write_status_format(writer, sheet_name: str, df: pd.DataFrame, status_col: str, formats: dict) -> None:
    if df.empty or status_col not in df.columns:
        return
    ws = writer.sheets[sheet_name]
    col_idx = list(df.columns).index(status_col)
    default_fmt = formats.get("FAIL") or next(iter(formats.values()))
    for row_num, val in enumerate(df[status_col], start=1):
        fmt = formats.get(str(val).upper(), default_fmt)
        ws.write(row_num, col_idx, val, fmt)


def run_pipeline_gstr3b(input_folder: str, output_dir: str, progress_cb: Callable | None = None):
    """Run the GSTR-3B pipeline.

    progress_cb(step, detail) is called after each pipeline stage when provided.
    When None, a Rich Live panel is rendered in the terminal (original behaviour).
    """
    os.makedirs(output_dir, exist_ok=True)
    error_log = []
    ui = PipelineUI("GSTR-3B Return Analyser")

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

        cache_file = os.path.join(output_dir, ".parse_cache_gstr3b.pkl")
        cache = _load_cache(cache_file)
        cache_lock = Lock()

        master_tables = {name: [] for name in _TABLE_NAMES}
        master_metadata = []
        all_exceptions = []
        done_count = 0

        with ThreadPoolExecutor(max_workers=min(4, len(pdf_files))) as executor:
            futures = {
                executor.submit(_parse_one_gstr3b, fpath, cache, cache_lock): fpath
                for fpath in pdf_files
            }
            for future in as_completed(futures):
                fpath = futures[future]
                filename = os.path.basename(fpath)
                done_count += 1
                ui.detail = (
                    f"{done_count}/{len(pdf_files)}  "
                    f"{(filename[:25] + '...') if len(filename) > 25 else filename}"
                )
                _push()

                try:
                    result, local_errors = future.result()
                except Exception as exc:
                    error_log.append({
                        "File": filename,
                        "Error_Type": type(exc).__name__,
                        "Message": str(exc),
                        "Action": "Could not process this file. Skipped.",
                    })
                    continue

                error_log.extend(local_errors)
                if result is None:
                    continue

                meta = dict(result["Metadata"])
                meta["Source_File"] = filename
                master_metadata.append(meta)

                gstin = meta.get("GSTIN", "Unknown")
                period = meta.get("Period_Year", "Unknown")

                file_tables = {
                    table_name: result[table_name]
                    for table_name in _TABLE_NAMES
                    if isinstance(result.get(table_name), pd.DataFrame)
                    and not result[table_name].empty
                }

                try:
                    audited_file_tables, file_exceptions = run_sanity_checks_gstr3b(
                        file_tables, gstin, period
                    )
                except Exception as exc:
                    error_log.append({
                        "File": filename,
                        "Error_Type": type(exc).__name__,
                        "Message": f"Sanity checks failed: {exc}",
                        "Action": "Checks skipped for this file. Data still written.",
                    })
                    audited_file_tables = file_tables
                    file_exceptions = []
                for exc in file_exceptions:
                    exc["Source_File"] = filename
                all_exceptions.extend(file_exceptions)

                for table_name in _TABLE_NAMES:
                    df = audited_file_tables.get(table_name)
                    if df is None:
                        df = result.get(table_name)
                    if not isinstance(df, pd.DataFrame) or df.empty:
                        continue
                    master_tables[table_name].append(_with_context(df, meta))

        _save_cache(cache_file, cache)

        df_metadata = pd.DataFrame(master_metadata)
        if not df_metadata.empty:
            df_metadata = df_metadata[[col for col in _META_COLS if col in df_metadata.columns]]

        ui.advance(f"{len(all_exceptions)} exception(s) flagged")
        _push()

        ui.advance("Building analytics fact tables...")
        _push()

        combined_audited = {
            table_name: pd.concat(df_list, ignore_index=True)
            for table_name, df_list in master_tables.items()
            if df_list
        }
        try:
            analytics_schema = create_analytics_schema_gstr3b(combined_audited)
        except Exception as exc:
            error_log.append({
                "File": "pipeline",
                "Error_Type": type(exc).__name__,
                "Message": f"Analytics build failed: {exc}",
                "Action": "Analytics fact sheets will be empty.",
            })
            analytics_schema = {}

        checksum_rows = []
        for ret in (df_metadata.to_dict("records") if not df_metadata.empty else []):
            gstin = ret.get("GSTIN", "")
            period = ret.get("Period_Year", "")
            for check_name in _KNOWN_CHECKS:
                matched = [
                    exc for exc in all_exceptions
                    if exc.get("GSTIN") == gstin
                    and exc.get("Period_Year") == period
                    and exc.get("Check") == check_name
                ]
                status = matched[0]["Sanity_Status"] if matched else "PASS"
                checksum_rows.append({
                    "GSTIN": gstin,
                    "Period_Year": period,
                    "Check": check_name,
                    "Status": status,
                })
        df_checksum = pd.DataFrame(checksum_rows)

        ui.advance("Writing workbooks...")
        _push()

        auditor_path = os.path.join(output_dir, "GSTR3B_Auditor_Master.xlsx")
        analytics_path = os.path.join(output_dir, "GSTR3B_Analytics_Master.xlsx")

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

                write_sheet(writer, df_metadata, "Metadata_Master")

                if all_exceptions:
                    df_exc = pd.DataFrame(all_exceptions)
                    _write_formatted_sheet(writer, df_exc, "EXCEPTIONS_LOG")
                    _write_status_format(writer, "EXCEPTIONS_LOG", df_exc, "Sanity_Status", status_formats)

                if not df_checksum.empty:
                    _write_formatted_sheet(writer, df_checksum, "Checksum_Status")
                    _write_status_format(writer, "Checksum_Status", df_checksum, "Status", status_formats)

                for table_name, df_list in master_tables.items():
                    if df_list:
                        sheet_title = table_name.replace("Table_", "T_")[:31]
                        write_sheet(writer, pd.concat(df_list, ignore_index=True), sheet_title)
        except ExcelWriteError:
            raise
        except Exception as exc:
            raise ExcelWriteError(
                f"Could not write '{os.path.basename(auditor_path)}'. "
                f"If it is open in Excel, close it and try again. ({exc})"
            ) from exc

        try:
            with pd.ExcelWriter(analytics_path, engine="xlsxwriter") as writer:
                build_executive_summary_gstr3b(writer, df_metadata, len(all_exceptions))
                write_sheet(writer, df_metadata, "Dim_Taxpayer_Calendar")
                for table_name, df in analytics_schema.items():
                    if not df.empty:
                        write_sheet(writer, df, table_name[:31])
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

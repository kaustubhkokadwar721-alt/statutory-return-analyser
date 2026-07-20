"""
Shared utility functions used across both GSTR-1 and GSTR-3B pipelines.
"""

import os
import re

from .constants import MONTH_ABBR


def clean_cell(val) -> str:
    """Strip PDF watermark chars (single uppercase letter + newline at start), normalise whitespace."""
    if val is None:
        return ''
    s = str(val)
    s = re.sub(r'^[A-Z]\n', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def to_float(val) -> float:
    """Parse Indian-format number string (commas, optional negative) to float. Returns 0.0 on failure."""
    s = clean_cell(val)
    if not s or s.lower() in ('-', '', 'nan', 'none', 'null', 'n/a'):
        return 0.0
    s = re.sub(r'[,\s]', '', s)
    try:
        result = float(s)
        return 0.0 if result != result else result  # guard against float NaN
    except (ValueError, TypeError):
        return 0.0


def make_period_year(period: str, fy: str) -> str:
    """Convert 'April', '2025-26' → 'Apr-25'.  Used by GSTR-1 metadata."""
    p = period.strip().lower()
    abbr = MONTH_ABBR.get(p, period[:3].capitalize())
    try:
        parts = fy.split('-')
        y1 = parts[0].strip()[-2:]
        y2 = parts[1].strip()[-2:] if len(parts) > 1 else str(int(y1) + 1).zfill(2)[-2:]
        yy = y2 if p in ('january', 'february', 'march') else y1
        return f"{abbr}-{yy}"
    except Exception:
        return f"{abbr}-??"


def calculate_period_year(period: str, year_str: str) -> str:
    """Convert 'June', '2025-26' → 'Jun-25'.  Used by GSTR-3B metadata."""
    if not period or period == "Unknown" or not year_str or "-" not in year_str:
        p = period[:3].capitalize() if period and period != "Unknown" else period
        return f"{p}-??"
    try:
        parts = year_str.split("-")
        y1 = parts[0].strip()[-2:]
        y2 = ("20" + parts[1].strip() if len(parts[1].strip()) == 2 else parts[1].strip())[-2:]
        p = period.strip().lower()
        abbr = MONTH_ABBR.get(p, MONTH_ABBR.get(p[:3], period[:3].capitalize()))
        yy = y2 if p[:3] in ('jan', 'feb', 'mar') else y1
        return f"{abbr}-{yy}"
    except Exception:
        return f"{period[:3].capitalize()}-??"


def check_file_locks(output_dir: str, filenames: list) -> str | None:
    """Return the filename if any target Excel file is open/locked in Excel, else None."""
    for fname in filenames:
        fpath = os.path.join(output_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'a'):
                    pass
            except PermissionError:
                return fname
    return None
